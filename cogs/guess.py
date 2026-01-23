import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
import asyncio
import logging
from PIL import Image, ImageOps
from io import BytesIO
from utils.image_helper import get_card_image_path
from config import CARDS_FILE, CHARACTERS_FILE, NICKNAMES_FILE, SONG_GUESS_DURATION

logger = logging.getLogger(__name__)

GUESS_PREFIX = "-g "
MAX_FAILS = 4


class GuessCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = set()
        self.cards = []
        self.chars = {}
        self.nicknames = {}
        self.load_data()

    def load_data(self):
        try:
            with open(CARDS_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                self.cards = [c for c in raw if c.get('prefix') and c['cardRarityType'] in ['rarity_3', 'rarity_4']]
            with open(CHARACTERS_FILE, 'r', encoding='utf-8') as f:
                self.chars = json.load(f)
            if NICKNAMES_FILE.exists():
                with open(NICKNAMES_FILE, 'r', encoding='utf-8') as f:
                    self.nicknames = json.load(f)
            logger.info("Guess: Data loaded successfully.")
        except FileNotFoundError as e:
            logger.error(f"Guess: Missing data file: {e.filename}")
        except json.JSONDecodeError as e:
            logger.error(f"Guess: Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Guess: Failed to load data: {e}")

    async def process_game_image(self, asset_name: str, is_trained: bool, difficulty: str) -> tuple[BytesIO | None, BytesIO | None]:
        """Process card image for guessing game."""
        local_path = await get_card_image_path(asset_name, is_trained)
        if not local_path:
            return None, None
        
        CROP_SIZE = 250
        
        # Use context manager to properly close the image file
        try:
            with Image.open(local_path) as full_img:
                full_img = full_img.convert("RGBA")
                w, h = full_img.size
                
                if w < CROP_SIZE or h < CROP_SIZE:
                    full_img = full_img.resize((max(w, CROP_SIZE), max(h, CROP_SIZE)))
                    w, h = full_img.size

                x = random.randint(0, w - CROP_SIZE)
                y = random.randint(0, h - CROP_SIZE)
                
                cropped = full_img.crop((x, y, x + CROP_SIZE, y + CROP_SIZE))
                
                if difficulty == 'hard':
                    cropped = ImageOps.grayscale(cropped)
                    
                crop_io = BytesIO()
                cropped.save(crop_io, format='PNG')
                crop_io.seek(0)
                
                # Save full image to buffer
                full_io = BytesIO()
                full_img.save(full_io, format='PNG')
                full_io.seek(0)
            
            return crop_io, full_io
            
        except OSError as e:
            logger.error(f"Failed to process image {asset_name}: {e}")
            return None, None

    @app_commands.command(name="guess", description="Đoán nhân vật!")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Dễ", value="easy"),
        app_commands.Choice(name="Khó", value="hard")
    ])
    async def guess(self, interaction: discord.Interaction, difficulty: str = "easy"):
        channel_id = interaction.channel_id
        if channel_id in self.active_channels:
            await interaction.response.send_message("Ai đó đang thử tài rồi, hãy chơi cùng họ nhé!", ephemeral=True)
            return
            
        self.active_channels.add(channel_id)
        await interaction.response.defer()

        try:
            card = random.choice(self.cards)
            is_trained = random.choice([True, False])
            
            crop_img, full_img = await self.process_game_image(card['assetbundleName'], is_trained, difficulty)
            
            if not crop_img:
                await interaction.followup.send("Lỗi load hình. Vui lòng thử lại sau.", ephemeral=True)
                self.active_channels.discard(channel_id)
                return

            char_data = self.chars.get(str(card['characterId']))
            if not char_data:
                await interaction.followup.send("Lỗi dữ liệu nhân vật.", ephemeral=True)
                self.active_channels.discard(channel_id)
                return
                
            possible_answers = [
                char_data['firstName'].lower(), 
                char_data['givenName'].lower(),
                f"{char_data['firstName']} {char_data['givenName']}".lower(),
                f"{char_data['givenName']} {char_data['firstName']}".lower()
            ]
            if str(card['characterId']) in self.nicknames:
                possible_answers.extend([n.lower() for n in self.nicknames[str(card['characterId'])]])

            logger.debug(f"Guess answer: {possible_answers[2]}")

            file = discord.File(crop_img, filename="guess.png")
            color = 0x808080 if difficulty == 'hard' else 0xF1C40F
            embed = discord.Embed(
                title=f"🖼️ ({difficulty.title()})", 
                description=f"Gõ `{GUESS_PREFIX}[name]` để đoán. Bạn có {SONG_GUESS_DURATION}s.", 
                color=color
            )
            embed.set_image(url="attachment://guess.png")
            
            # Create view with working Give Up button
            view = GiveUpView(channel_id, self, char_data, card, full_img)
            msg = await interaction.followup.send(embed=embed, file=file, view=view)
            view.message = msg

            winner = None
            reason = "timeout"
            fails = 0
            
            def check(m): 
                return m.channel.id == channel_id and not m.author.bot and m.content.lower().startswith(GUESS_PREFIX)
            
            end_time = asyncio.get_event_loop().time() + SONG_GUESS_DURATION
            
            while asyncio.get_event_loop().time() < end_time and not view.gave_up:
                remaining = end_time - asyncio.get_event_loop().time()
                try:
                    guess_msg = await self.bot.wait_for('message', check=check, timeout=min(remaining, 1.0))
                    guess = guess_msg.content[len(GUESS_PREFIX):].strip().lower()
                    
                    if guess in possible_answers or (len(guess) > 2 and any(guess in ans for ans in possible_answers)):
                        winner = guess_msg.author
                        reason = "win"
                        await guess_msg.add_reaction("✅")
                        break
                    else:
                        fails += 1
                        await guess_msg.add_reaction("❌")
                        if fails >= MAX_FAILS:
                            reason = "failed"
                            break
                        
                except asyncio.TimeoutError:
                    continue
            
            if view.gave_up:
                reason = "gave_up"
            
            # Prepare result
            result_file = discord.File(full_img, filename="reveal.png")
            result_embed = discord.Embed(description=f"Đáp án: **{char_data['firstName']} {char_data['givenName']}**")
            result_embed.set_image(url="attachment://reveal.png")
            result_embed.add_field(name="Card", value=card.get('prefix', 'Unknown'))
            
            if reason == "win":
                result_embed.title = f"Đúng rồi! Xin chúc mừng {winner.display_name}"
                result_embed.color = 0x2ECC71
            elif reason == "failed":
                result_embed.title = f"Game Over. Bạn chỉ được phép đoán sai {MAX_FAILS} lần!"
                result_embed.color = 0xE74C3C
            elif reason == "gave_up":
                result_embed.title = "Đã bỏ cuộc!"
                result_embed.color = 0xE74C3C
            else:
                result_embed.title = "Hết giờ rồi!"
                result_embed.color = 0xE74C3C

            view.disable_all()
            await interaction.followup.send(embed=result_embed, file=result_file)
            await msg.edit(view=view)

        except Exception as e:
            logger.error(f"Guess game error: {e}")
            await interaction.followup.send("Error occurred.", ephemeral=True)
        finally:
            self.active_channels.discard(channel_id)


class GiveUpView(discord.ui.View):
    """View with a working Give Up button."""
    
    def __init__(self, channel_id: int, cog: GuessCog, char_data: dict, card: dict, full_img: BytesIO):
        super().__init__(timeout=SONG_GUESS_DURATION + 5)
        self.channel_id = channel_id
        self.cog = cog
        self.char_data = char_data
        self.card = card
        self.full_img = full_img
        self.gave_up = False
        self.message = None
    
    @discord.ui.button(label="Give Up", style=discord.ButtonStyle.danger)
    async def give_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle give up button click."""
        self.gave_up = True
        button.disabled = True
        await interaction.response.defer()
    
    def disable_all(self):
        """Disable all buttons."""
        for item in self.children:
            item.disabled = True
    
    async def on_timeout(self):
        """Handle view timeout."""
        self.disable_all()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(GuessCog(bot))
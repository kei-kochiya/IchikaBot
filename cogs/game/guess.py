import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
import asyncio
import logging
from PIL import Image, ImageOps, ImageFilter
from io import BytesIO
from utils.media.image_helper import get_card_image_path
from config import SONG_GUESS_DURATION
from utils.data.card_data import card_data
from utils.data.game_data import game_data

logger = logging.getLogger(__name__)

GUESS_PREFIX = "-g "
MAX_FAILS = 4


class GuessCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = set()
        # References to shared singletons — no per-cog loading
        self.cards = card_data.pool_3_4

    def load_data(self):
        """Card/character data managed by shared singletons."""
        self.cards = card_data.pool_3_4

    def get_display_prefix(self, card: dict) -> str:
        return card_data.get_display_prefix(card)

    def build_answer_list(self, char_id: int | str) -> list[str]:
        char = game_data.get_character(char_id)
        if not char:
            return []
        fn = char.get('firstName', '').lower()
        gn = char.get('givenName', '').lower()
        answers = {fn, gn, f"{fn} {gn}".strip(), f"{gn} {fn}".strip()}
        for nick in game_data.nicknames.get(str(char_id), []):
            answers.add(nick.lower())
        return list(answers)

    async def process_game_image(self, asset_name: str, is_trained: bool, mode: str) -> tuple[BytesIO | None, BytesIO | None, str]:
        """Process card image for guessing game. Returns (game_img_io, full_img_io, effect_name)."""
        local_path = await get_card_image_path(asset_name, is_trained)
        if not local_path:
            return None, None, ""
        
        CROP_SIZE = 250
        
        try:
            with Image.open(local_path) as full_img:
                full_img = full_img.convert("RGBA")
                w, h = full_img.size
                
                if w < CROP_SIZE or h < CROP_SIZE:
                    full_img = full_img.resize((max(w, CROP_SIZE), max(h, CROP_SIZE)))
                    w, h = full_img.size
                
                effect_used = "Normal"
                game_img = None
                
                if mode == 'random':
                    effect = random.choice(['crop_bw', 'pixelate', 'blur', 'negative'])
                else:
                    effect = 'crop'
                    
                if effect == 'crop' or effect == 'crop_bw':
                    x = random.randint(0, w - CROP_SIZE)
                    y = random.randint(0, h - CROP_SIZE)
                    game_img = full_img.crop((x, y, x + CROP_SIZE, y + CROP_SIZE))
                    if effect == 'crop_bw':
                        game_img = ImageOps.grayscale(game_img)
                        effect_used = "Trắng đen"
                    else:
                        effect_used = "Crop"
                        
                elif effect == 'pixelate':
                    # Scale down then up to create pixelation effect
                    small = full_img.resize((48, 48), Image.NEAREST)
                    game_img = small.resize((w, h), Image.NEAREST)
                    effect_used = "Pixelate"
                    
                elif effect == 'blur':
                    game_img = full_img.filter(ImageFilter.GaussianBlur(radius=25))
                    effect_used = "Blur"
                    
                elif effect == 'negative':
                    # Invert requires RGB
                    rgb_img = full_img.convert("RGB")
                    game_img = ImageOps.invert(rgb_img)
                    effect_used = "Âm bản"

                game_io = BytesIO()
                game_img.save(game_io, format='PNG')
                game_io.seek(0)
                
                # Save full image to buffer
                full_io = BytesIO()
                full_img.save(full_io, format='PNG')
                full_io.seek(0)
            
            return game_io, full_io, effect_used
            
        except OSError as e:
            logger.error(f"Failed to process image {asset_name}: {e}")
            return None, None, ""

    @app_commands.command(name="guess", description="Đoán nhân vật qua hình ảnh!")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Normal", value="normal"),
        app_commands.Choice(name="Random", value="random")
    ])
    async def guess(self, interaction: discord.Interaction, mode: str = "normal"):
        channel_id = interaction.channel_id
        if channel_id in self.active_channels:
            await interaction.response.send_message("Ai đó đang thử tài rồi, hãy chơi cùng họ nhé!", ephemeral=True)
            return
            
        self.active_channels.add(channel_id)
        await interaction.response.defer()

        try:
            card = random.choice(self.cards)
            is_trained = random.choice([True, False])
            
            game_img, full_img, effect_name = await self.process_game_image(card['assetbundleName'], is_trained, mode)
            
            if not game_img:
                await interaction.followup.send("Lỗi load hình. Vui lòng thử lại sau.", ephemeral=True)
                self.active_channels.discard(channel_id)
                return

            char_data = game_data.characters.get(str(card['characterId']))
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
            nicks = game_data.nicknames.get(str(card['characterId']), [])
            if nicks:
                possible_answers.extend([n.lower() for n in nicks])

            logger.debug(f"Guess answer: {possible_answers[2]}")

            file = discord.File(game_img, filename="guess.png")
            embed = discord.Embed(
                title=f"Đoán nhân vật", 
                description=f"Gõ `{GUESS_PREFIX}[name]` để đoán. Bạn có {SONG_GUESS_DURATION}s.", 
                color=0xF1C40F if mode == 'normal' else 0x9B59B6
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
            
            end_time = asyncio.get_running_loop().time() + SONG_GUESS_DURATION
            
            while asyncio.get_running_loop().time() < end_time and not view.gave_up:
                remaining = end_time - asyncio.get_running_loop().time()
                try:
                    guess_msg = await self.bot.wait_for('message', check=check, timeout=min(remaining, 1.0))
                    guess = guess_msg.content[len(GUESS_PREFIX):].strip().lower()
                    
                    if guess in possible_answers or (len(guess) > 2 and any(guess in ans for ans in possible_answers)):
                        winner = guess_msg.author
                        reason = "win"
                        asyncio.create_task(guess_msg.add_reaction("✅"))
                        break
                    else:
                        fails += 1
                        asyncio.create_task(guess_msg.add_reaction("❌"))
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
            result_embed.add_field(name="Card", value=self.get_display_prefix(card))
            
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
"""
Gacha Cog - Gacha simulation for Project Sekai.
"""
import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import logging
import aiofiles
from PIL import Image, ImageDraw
from io import BytesIO

from utils.image_helper import get_card_image_path
from utils.game_data import get_unit_color_hex
from config import (
    CARDS_FILE, RARITY_ICONS, PITY_FILE,
    PITY_THRESHOLD, GACHA_RATES, SharedResources
)

logger = logging.getLogger(__name__)


class GachaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cards = []
        self.load_data()
        
        self.cards_2 = [c for c in self.cards if c['cardRarityType'] == 'rarity_2' and c.get('prefix')]
        self.cards_3 = [c for c in self.cards if c['cardRarityType'] == 'rarity_3' and c.get('prefix')]
        self.cards_4 = [c for c in self.cards if c['cardRarityType'] == 'rarity_4' and c.get('prefix')]

    def load_data(self):
        try:
            with open(CARDS_FILE, 'r', encoding='utf-8') as f:
                self.cards = json.load(f)
            logger.info("Gacha: Data loaded successfully.")
        except FileNotFoundError as e:
            logger.error(f"Gacha: Missing data file: {e.filename}")
        except Exception as e:
            logger.error(f"Gacha: Failed to load game data: {e}")

    async def get_user_pity(self, user_id: int) -> int:
        """Get user's current pity count with async file access."""
        user_id_str = str(user_id)
        lock = SharedResources.get_pity_lock()
        
        async with lock:
            if not PITY_FILE.exists():
                async with aiofiles.open(PITY_FILE, 'w') as f:
                    await f.write('{}')
                return 0
            
            try:
                async with aiofiles.open(PITY_FILE, 'r') as f:
                    data = json.loads(await f.read())
                return data.get(user_id_str, 0)
            except json.JSONDecodeError:
                logger.warning("Pity file corrupted, resetting...")
                return 0
            except Exception as e:
                logger.error(f"Error reading pity data: {e}")
                return 0

    async def update_user_pity(self, user_id: int, count: int):
        """Update user's pity count with async file access and locking."""
        user_id_str = str(user_id)
        lock = SharedResources.get_pity_lock()
        
        async with lock:
            data = {}
            if PITY_FILE.exists():
                try:
                    async with aiofiles.open(PITY_FILE, 'r') as f:
                        data = json.loads(await f.read())
                except Exception as e:
                    logger.warning(f"Error reading pity file, starting fresh: {e}")
            
            data[user_id_str] = count
            
            try:
                async with aiofiles.open(PITY_FILE, 'w') as f:
                    await f.write(json.dumps(data, indent=4))
            except Exception as e:
                logger.error(f"Error saving pity data: {e}")

    async def pull_one_card(self, user_id: int, is_guaranteed_slot: bool = False):
        """Pull a single card with pity system."""
        current_pity = await self.get_user_pity(user_id)
        current_pity += 1 
        
        card = None
        
        if current_pity >= PITY_THRESHOLD:
            card = random.choice(self.cards_4)
            current_pity = 0 
        else:
            rand = random.random()
            
            if is_guaranteed_slot:
                total_rate = GACHA_RATES['rarity_4'] + GACHA_RATES['rarity_3']
                rate_4_norm = GACHA_RATES['rarity_4'] / total_rate
                
                if rand < rate_4_norm:
                    card = random.choice(self.cards_4)
                    current_pity = 0
                else:
                    card = random.choice(self.cards_3)
            else:
                if rand < GACHA_RATES['rarity_4']:
                    card = random.choice(self.cards_4)
                    current_pity = 0
                elif rand < (GACHA_RATES['rarity_4'] + GACHA_RATES['rarity_3']):
                    card = random.choice(self.cards_3)
                else:
                    card = random.choice(self.cards_2)

        await self.update_user_pity(user_id, current_pity)
        return card

    gacha_group = app_commands.Group(name="gacha", description="Mô phỏng Gacha Project Sekai")

    @gacha_group.command(name="pull", description="Thử vận may")
    @app_commands.choices(amount=[
        app_commands.Choice(name="Quay 1 lần", value=1),
        app_commands.Choice(name="Quay 10 lần", value=10)
    ])
    async def pull(self, interaction: discord.Interaction, amount: int = 10):
        await interaction.response.defer()
        user_id = interaction.user.id
        
        results = []
        
        if amount == 1:
            results.append(await self.pull_one_card(user_id))
        else:
            for _ in range(9):
                results.append(await self.pull_one_card(user_id))
            results.append(await self.pull_one_card(user_id, is_guaranteed_slot=True))

        final_pity = await self.get_user_pity(user_id)
        best_card = max(results, key=lambda x: x['cardRarityType'])

        if amount == 1:
            card = results[0]
            local_path = await get_card_image_path(card['assetbundleName'])
            
            if not local_path:
                await interaction.followup.send("Lỗi tải ảnh. Vui lòng thử lại.")
                return
                
            f = discord.File(local_path, filename="card.png")
            color = get_unit_color_hex(card['characterId'])
            rarity_icon = RARITY_ICONS.get(card['cardRarityType'], '')

            embed = discord.Embed(
                title=f"{rarity_icon} Kết Quả Gacha",
                description=f"**{card['prefix']}**",
                color=discord.Color.from_str(color)
            )
            embed.set_image(url="attachment://card.png")
            embed.set_footer(text=f"Pity: {final_pity}/{PITY_THRESHOLD}")
            
            await interaction.followup.send(embed=embed, file=f)
            
        else:
            THUMB_W, THUMB_H = 192, 110
            PADDING, BORDER, COLS = 20, 5, 5
            canvas_w = (THUMB_W * COLS) + (PADDING * (COLS + 1))
            canvas_h = (THUMB_H * 2) + (PADDING * 3)
            
            bg = Image.new('RGBA', (canvas_w, canvas_h), (44, 47, 51, 255))
            draw = ImageDraw.Draw(bg)
            
            def get_border_color(rarity):
                if rarity == 'rarity_4': return '#9B59B6'
                if rarity == 'rarity_3': return '#F1C40F'
                return '#3498DB'

            for i, card in enumerate(results):
                row, col = i // COLS, i % COLS
                x = PADDING + col * (THUMB_W + PADDING)
                y = PADDING + row * (THUMB_H + PADDING)
                
                draw.rectangle([x - BORDER, y - BORDER, x + THUMB_W + BORDER, y + THUMB_H + BORDER], 
                              fill=get_border_color(card['cardRarityType']))
                
                path = await get_card_image_path(card['assetbundleName'])
                if path:
                    try:
                        with Image.open(path) as thumb:
                            thumb = thumb.resize((THUMB_W, THUMB_H))
                            bg.paste(thumb, (x, y))
                    except OSError as e:
                        logger.warning(f"Failed to open thumbnail: {e}")

            out_buffer = BytesIO()
            bg.save(out_buffer, format='PNG')
            out_buffer.seek(0)
            f = discord.File(out_buffer, filename="gacha_10.png")
            
            c4 = len([c for c in results if c['cardRarityType'] == 'rarity_4'])
            c3 = len([c for c in results if c['cardRarityType'] == 'rarity_3'])
            
            color = get_unit_color_hex(best_card['characterId'])
            
            embed = discord.Embed(
                title=f"Kết quả 10 lần quay của {interaction.user.name}",
                description=f"**4⭐:** {c4} | **3⭐:** {c3}",
                color=discord.Color.from_str(color)
            )
            embed.set_image(url="attachment://gacha_10.png")
            embed.set_footer(text=f"Pity: {final_pity}/{PITY_THRESHOLD}")

            await interaction.followup.send(embed=embed, file=f)

    @gacha_group.command(name="pity", description="Kiểm tra số lần quay đã tích lũy")
    async def check_pity(self, interaction: discord.Interaction):
        """Check current pity count."""
        pity = await self.get_user_pity(interaction.user.id)
        remaining = PITY_THRESHOLD - pity
        
        embed = discord.Embed(
            title="📊 Thông tin Pity",
            description=f"**Đã quay:** {pity}/{PITY_THRESHOLD}\n**Còn lại:** {remaining} lần để đảm bảo 4⭐",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(GachaCog(bot))
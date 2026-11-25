"""Project Sekai account link, Transfer-ID sync, profile lookup, and Best 30 (B30) commands.

Heavy PJSK dependencies (`cryptography`, `msgpack`, `PIL`) are imported lazily inside callbacks.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.core import database
from utils.data.song_data import song_data
from utils.media.image_helper import get_song_jacket_path
from utils.pjsk.ui import (
    LinkUserIDModal,
    TransferIDModal,
    cleanup_transfer_lock,
    deliver_dm_embed,
    get_transfer_lock,
    safe_display_name,
)

logger = logging.getLogger(__name__)

REGION_CHOICES = [
    app_commands.Choice(name="EN (Global)", value="en"),
    app_commands.Choice(name="JP (Japan)", value="jp"),
]


class PJSKCog(commands.Cog):
    """Project Sekai account link, Transfer-ID sync, profile, and Best 30 rating."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    pjsk_group = app_commands.Group(
        name="pjsk",
        description="Liên kết tài khoản Project Sekai, đồng bộ dữ liệu và xem B30",
    )

    @pjsk_group.command(name="link", description="Liên kết tài khoản PJSK (EN/JP) qua Bio")
    @app_commands.describe(region="Chọn server (EN hoặc JP)")
    @app_commands.choices(region=REGION_CHOICES)
    async def pjsk_link(self, interaction: discord.Interaction, region: str = "en") -> None:
        await interaction.response.send_modal(LinkUserIDModal(region.lower()))

    @pjsk_group.command(
        name="unlink", description="Hủy liên kết tài khoản PJSK và xóa dữ liệu đã lưu"
    )
    @app_commands.describe(region="Chọn server (EN hoặc JP)")
    @app_commands.choices(region=REGION_CHOICES)
    async def pjsk_unlink(self, interaction: discord.Interaction, region: str = "en") -> None:
        reg = region.lower()
        op_lock = get_transfer_lock(interaction.user.id, reg)
        if op_lock.locked():
            await interaction.response.send_message(
                f"Đang có phiên sync/recover chạy cho server **{reg.upper()}**. "
                "Vui lòng đợi hoàn tất trước khi hủy liên kết.",
                ephemeral=True,
            )
            return
        cleanup_transfer_lock(interaction.user.id, reg, op_lock)

        pending_recovery = await database.get_pjsk_recovery(interaction.user.id, reg)
        if pending_recovery is not None:
            await interaction.response.send_message(
                f"Bạn đang có mã khôi phục Transfer ID chưa nhận cho server **{reg.upper()}**! "
                f"Hãy chạy `/pjsk recover region:{reg}` trước để lấy lại tài khoản rồi mới hủy liên kết.",
                ephemeral=True,
            )
            return

        removed = await database.delete_pjsk_link(interaction.user.id, reg)
        if not removed:
            await interaction.response.send_message(
                f"Bạn chưa liên kết tài khoản PJSK **{reg.upper()}** nào.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Đã hủy liên kết và xóa dữ liệu FC/AP của server **{reg.upper()}**.",
            ephemeral=True,
        )

    @pjsk_group.command(name="profile", description="Xem hồ sơ Project Sekai đã liên kết")
    @app_commands.checks.cooldown(1, 5.0)
    @app_commands.describe(
        region="Chọn server (EN hoặc JP)",
        user="Người dùng Discord muốn xem (mặc định là bạn)",
    )
    @app_commands.choices(region=REGION_CHOICES)
    async def pjsk_profile(
        self,
        interaction: discord.Interaction,
        region: str = "en",
        user: discord.User | None = None,
    ) -> None:
        target = user or interaction.user
        reg = region.lower()
        link = await database.get_pjsk_link(target.id, reg)
        if not link:
            who = (
                "Bạn"
                if target.id == interaction.user.id
                else f"**{safe_display_name(target.display_name)}**"
            )
            await interaction.response.send_message(
                f"{who} chưa liên kết tài khoản PJSK **{reg.upper()}**. Dùng `/pjsk link region:{reg}` để liên kết.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await interaction.response.defer()
        from utils.pjsk.client import PJSKError, get_pjsk_client

        try:
            client = get_pjsk_client(reg)
            profile = await client.get_profile(link["pjsk_user_id"])
        except PJSKError as exc:
            await interaction.followup.send(f"Không thể tải hồ sơ PJSK: {exc}")
            return

        safe_bio = (
            discord.utils.escape_markdown(discord.utils.escape_mentions(profile.bio))[:1024]
            if profile.bio
            else "*Không có Bio*"
        )
        embed = discord.Embed(
            title=f"{safe_display_name(profile.name)}  [{reg.upper()}]"[:256],
            description=safe_bio,
            color=discord.Color.from_rgb(102, 178, 255),
        )
        embed.add_field(name="User ID", value=f"`{profile.user_id}`", inline=True)
        embed.add_field(name="Rank", value=f"**🎵 {profile.rank}**", inline=True)
        if profile.total_power:
            embed.add_field(name="Total Power", value=f"{profile.total_power:,}", inline=True)

        diff_order = ("expert", "master", "append")
        lines = []
        for diff in diff_order:
            counts = profile.clear_counts.get(diff)
            if counts:
                lines.append(
                    f"**{diff.capitalize()}**: Clear `{counts['clear']}` · FC `{counts['fc']}` · AP `{counts['ap']}`"
                )
        if lines:
            embed.add_field(name="Thành tích bài hát", value="\n".join(lines), inline=False)

        synced_at = int(link.get("synced_at") or 0)
        sync_txt = f"<t:{synced_at}:R>" if synced_at > 0 else "Chưa đồng bộ (`/pjsk sync`)"
        embed.add_field(name="Đồng bộ B30 lần cuối", value=sync_txt, inline=False)
        await interaction.followup.send(embed=embed)

    @pjsk_group.command(
        name="sync",
        description="Đồng bộ bài FC/AP qua Transfer ID (trong DM) và nhận lại Transfer ID mới",
    )
    @app_commands.describe(region="Chọn server (EN hoặc JP)")
    @app_commands.choices(region=REGION_CHOICES)
    async def pjsk_sync(self, interaction: discord.Interaction, region: str = "en") -> None:
        reg = region.lower()
        link = await database.get_pjsk_link(interaction.user.id, reg)
        if not link:
            await interaction.response.send_message(
                f"Bạn cần liên kết tài khoản PJSK **{reg.upper()}** trước bằng `/pjsk link region:{reg}`.",
                ephemeral=True,
            )
            return

        from utils.pjsk.client import INHERIT_TOKEN_ENV, get_pjsk_client

        client = get_pjsk_client(reg)
        if not client.inherit_token:
            env_name = INHERIT_TOKEN_ENV[reg]
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"Chưa cấu hình Transfer Token cho {reg.upper()}",
                    description=(
                        f"Chủ bot chưa thiết lập biến môi trường `{env_name}` trong `.env` "
                        "(secret dùng để ký header `x-inherit-id-verify-token` khi đăng nhập Transfer ID)."
                    ),
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            TransferIDModal(region=reg, pjsk_user_id=link["pjsk_user_id"])
        )

    @pjsk_group.command(
        name="recover",
        description="Khôi phục & tạo lại Transfer ID mới nếu quá trình /pjsk sync bị gián đoạn",
    )
    @app_commands.describe(region="Chọn server (EN hoặc JP)")
    @app_commands.choices(region=REGION_CHOICES)
    async def pjsk_recover(self, interaction: discord.Interaction, region: str = "en") -> None:
        reg = region.lower()
        op_lock = get_transfer_lock(interaction.user.id, reg)
        if op_lock.locked():
            await interaction.response.send_message(
                f"Đang có một phiên sync/recover khác chạy cho server **{reg.upper()}**. Vui lòng đợi hoàn tất.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            async with op_lock:
                rec = await database.get_pjsk_recovery(interaction.user.id, reg)
                if not rec:
                    await interaction.followup.send(
                        f"Không có phiên transfer nào đang chờ khôi phục cho server **{reg.upper()}**.",
                        ephemeral=True,
                    )
                    return

                try:
                    dm_msg = await interaction.user.send(
                        f"Đang tạo lại Transfer ID khôi phục cho server **{reg.upper()}**..."
                    )
                except discord.HTTPException:
                    await interaction.followup.send(
                        "Không thể gửi DM cho bạn. Hãy bật nhận DM rồi thử lại `/pjsk recover`.",
                        ephemeral=True,
                    )
                    return

                from utils.pjsk.client import PJSKError, get_pjsk_client

                try:
                    client = get_pjsk_client(reg)
                    new_tid, new_pw = await client.reissue_transfer_from_credential(
                        rec["pjsk_user_id"], rec["credential"]
                    )
                except PJSKError as exc:
                    await dm_msg.edit(content=f"Khôi phục thất bại: {str(exc)[:500]}")
                    await interaction.followup.send(
                        "Khôi phục thất bại — xem chi tiết trong DM.", ephemeral=True
                    )
                    return
                except Exception as exc:
                    logger.exception("Unexpected error during /pjsk recover: %s", exc)
                    await dm_msg.edit(
                        content="Khôi phục gặp lỗi không mong muốn. Vui lòng thử lại sau ít phút."
                    )
                    await interaction.followup.send(
                        "Khôi phục gặp lỗi ngoài ý muốn — xem chi tiết trong DM.", ephemeral=True
                    )
                    return

                rec_embed = discord.Embed(
                    title=f"Khôi phục Transfer ID thành công ({reg.upper()})",
                    description=(
                        "Hãy dùng thông tin bên dưới để đăng nhập lại vào game:\n\n"
                        f"**Transfer ID mới:** `{new_tid}`\n"
                        f"**Mật khẩu mới:** `{new_pw}`\n\n"
                        "**Sau khi vào lại game, hãy tạo lại Transfer ID mới để bảo mật.**"
                    ),
                    color=discord.Color.green(),
                )
                delivered = await deliver_dm_embed(
                    embed=rec_embed,
                    message=dm_msg,
                    user=interaction.user,
                )
                if delivered:
                    await database.delete_pjsk_recovery(interaction.user.id, reg)
                    await interaction.followup.send(
                        "Đã gửi Transfer ID khôi phục mới vào DM của bạn!", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Không thể gửi kết quả khôi phục qua DM. Vui lòng thử `/pjsk recover` lại sau.",
                        ephemeral=True,
                    )
        finally:
            cleanup_transfer_lock(interaction.user.id, reg, op_lock)

    async def _send_b30(
        self,
        interaction: discord.Interaction,
        region: str,
        user: discord.User | None,
    ) -> None:
        target = user or interaction.user
        reg = region.lower()
        link = await database.get_pjsk_link(target.id, reg)
        if not link:
            who = (
                "Bạn"
                if target.id == interaction.user.id
                else f"**{safe_display_name(target.display_name)}**"
            )
            await interaction.response.send_message(
                f"{who} chưa liên kết tài khoản PJSK **{reg.upper()}**. Dùng `/pjsk link region:{reg}` trước nhé.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        clears = await database.get_pjsk_clears(target.id, reg)
        if not clears:
            who = (
                "Bạn"
                if target.id == interaction.user.id
                else f"**{safe_display_name(target.display_name)}**"
            )
            await interaction.response.send_message(
                f"{who} chưa có dữ liệu bài hát cho **{reg.upper()}**. "
                f"Hãy dùng `/pjsk sync region:{reg}` để đồng bộ trước nhé.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await interaction.response.defer()
        from utils.pjsk.b30_render import render_b30_image
        from utils.pjsk.constants import compute_b30, get_chart_constants

        try:
            constants = await get_chart_constants()
        except Exception as exc:
            logger.error("Failed to fetch pjskb30 constants: %s", exc)
            await interaction.followup.send(
                "Không thể tải bảng hằng số bài hát từ `pjskb30`. Vui lòng thử lại sau ít phút."
            )
            return

        summary = compute_b30(
            clears,
            constants,
            song_lookup=song_data.songs_jp_by_id,
            en_title_lookup=song_data.songs_en_meta,
        )

        # Fetch unique song jackets concurrently (bounded to avoid overwhelming CDN)
        unique_songs = {e.song_id: e.assetbundle_name for e in summary.entries}
        sem = asyncio.Semaphore(8)

        async def _fetch_jacket(sid: int, asset: str | None) -> tuple[int, str | None]:
            async with sem:
                return sid, await get_song_jacket_path(sid, asset)

        jacket_pairs = await asyncio.gather(
            *(_fetch_jacket(sid, asset) for sid, asset in unique_songs.items())
        )
        jacket_paths = dict(jacket_pairs)

        raw_name = link.get("pjsk_name") or target.display_name
        loop = asyncio.get_running_loop()
        img_bytes = await loop.run_in_executor(
            None,
            lambda: render_b30_image(
                summary,
                jacket_paths,
                player_name=raw_name,
                region=reg,
            ),
        )

        synced_at = int(link.get("synced_at") or 0)
        sync_note = f" · Cập nhật <t:{synced_at}:R>" if synced_at > 0 else ""
        caption = (
            f"**{safe_display_name(raw_name)}** (`{reg.upper()}`) — **B30 Rating: {summary.ranking:.2f}** "
            f"({len(summary.entries)}/30 charts: **{summary.ap_count}** AP · **{summary.fc_count}** FC)"
            f"{sync_note}"
        )
        await interaction.followup.send(
            content=caption,
            file=discord.File(img_bytes, filename=f"b30_{reg}_{link['pjsk_user_id']}.jpg"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @pjsk_group.command(name="b30", description="Xem bảng Best 30 (B30) rating Project Sekai")
    @app_commands.checks.cooldown(1, 5.0)
    @app_commands.describe(
        region="Chọn server (EN hoặc JP)",
        user="Người dùng Discord muốn xem (mặc định là bạn)",
    )
    @app_commands.choices(region=REGION_CHOICES)
    async def pjsk_b30(
        self,
        interaction: discord.Interaction,
        region: str = "en",
        user: discord.User | None = None,
    ) -> None:
        await self._send_b30(interaction, region, user)

    @app_commands.command(name="b30", description="Xem nhanh bảng Best 30 (B30) Project Sekai")
    @app_commands.checks.cooldown(1, 5.0)
    @app_commands.describe(
        region="Chọn server (EN hoặc JP)",
        user="Người dùng Discord muốn xem (mặc định là bạn)",
    )
    @app_commands.choices(region=REGION_CHOICES)
    async def b30_shortcut(
        self,
        interaction: discord.Interaction,
        region: str = "en",
        user: discord.User | None = None,
    ) -> None:
        await self._send_b30(interaction, region, user)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PJSKCog(bot))

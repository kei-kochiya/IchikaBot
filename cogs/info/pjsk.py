"""
Project Sekai Account Link, Transfer-ID Sync, Profile, and B30 Cog.

Faithful recreation of Sbotga's account linking & B30 workflow for both EN and JP servers:
  - /pjsk link [region]       : Link PJSK User ID via in-game Bio verification.
  - /pjsk unlink [region]     : Unlink PJSK account and delete saved clears.
  - /pjsk profile [region]    : Show live PJSK player profile.
  - /pjsk sync [region]       : Sync FC/AP data via Transfer ID (in DM) and return a new Transfer ID.
  - /pjsk recover [region]    : Crash-recovery to re-issue a Transfer ID if a sync was interrupted.
  - /pjsk import [region]     : Import FC/AP clears from an exported suite.json file.
  - /pjsk b30 [region] [user] : Render Best 30 rating image using pjskb30 chart constants.
  - /b30 [region] [user]      : Top-level shortcut for /pjsk b30.

All heavy PJSK dependencies (`cryptography`, `msgpack`, `PIL`) are imported lazily inside
command callbacks so bot startup RAM stays minimal.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import sqlite3
import string
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils.core import database
from utils.data.song_data import song_data
from utils.media.image_helper import get_song_jacket_path

logger = logging.getLogger(__name__)

REGION_CHOICES = [
    app_commands.Choice(name="EN (Global)", value="en"),
    app_commands.Choice(name="JP (Japan)", value="jp"),
]

_VERIFY_ALPHABET = string.ascii_uppercase + string.digits
_MAX_SUITE_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB safety limit for suite.json uploads
_MAX_INT64 = (1 << 63) - 1

# Per-(discord_id, region) lock serializing /pjsk sync and /pjsk recover
_transfer_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _get_transfer_lock(discord_id: int, region: str) -> asyncio.Lock:
    key = (discord_id, region.lower())
    lock = _transfer_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _transfer_locks[key] = lock
    return lock


def _generate_verify_code() -> str:
    suffix = "".join(secrets.choice(_VERIFY_ALPHABET) for _ in range(6))
    return f"ICHIKA-{suffix}"


def _safe_inline_code(text: str) -> str:
    """Escape backticks so arbitrary player strings cannot break inline code spans."""
    return (text or "").replace("`", "'")


def _safe_display_name(name: str) -> str:
    cleaned = " ".join((name or "Player").split())[:32] or "Player"
    return discord.utils.escape_markdown(discord.utils.escape_mentions(cleaned))


def _pjsk_created_timestamp_tag(user_id: int) -> str:
    from utils.pjsk.crypto import pjsk_id_to_created_ts

    ts = pjsk_id_to_created_ts(user_id)
    return f"<t:{ts}:R>" if ts else "Không rõ"


async def _deliver_dm_embed(
    *,
    embed: discord.Embed,
    interaction: discord.Interaction | None = None,
    message: discord.Message | None = None,
    user: discord.abc.Messageable | None = None,
    view: discord.ui.View | None = None,
) -> bool:
    """Deliver a critical DM embed (e.g. new Transfer ID) with resilient fallbacks.

    Tries: interaction.edit_original_response -> message.edit -> user.send.
    Returns True if delivered via any channel.
    """
    if interaction is not None:
        try:
            await interaction.edit_original_response(embed=embed, view=view)
            return True
        except Exception as exc:
            logger.warning("DM delivery via edit_original_response failed: %s", exc)

    if message is not None:
        try:
            await message.edit(content=None, embed=embed, view=view)
            return True
        except Exception as exc:
            logger.warning("DM delivery via message.edit failed: %s", exc)

    if user is not None:
        try:
            await user.send(embed=embed)
            return True
        except Exception as exc:
            logger.error("DM delivery via user.send fallback failed: %s", exc)

    return False


# ── Views & Modals for Account Linking ────────────────────────────────────────


class LinkVerifyView(discord.ui.View):
    """Button view that re-fetches the player's Bio to complete account linking."""

    def __init__(
        self,
        *,
        discord_id: int,
        region: str,
        pjsk_user_id: int,
        verify_code: str,
        initial_name: str,
        timeout: float = 300.0,
    ):
        super().__init__(timeout=timeout)
        self.discord_id = discord_id
        self.region = region
        self.pjsk_user_id = pjsk_user_id
        self.verify_code = verify_code
        self.initial_name = initial_name
        self._lock = asyncio.Lock()
        self._done = False

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="Xác minh Bio", style=discord.ButtonStyle.success)
    async def verify_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                "Chỉ người gọi lệnh mới có thể bấm nút này.", ephemeral=True
            )
            return
        if self._done or self._lock.locked():
            await interaction.response.send_message(
                "Yêu cầu xác minh đang được xử lý hoặc đã hoàn tất.", ephemeral=True
            )
            return

        async with self._lock:
            if self._done:
                await interaction.response.send_message(
                    "Phiên xác minh này đã kết thúc.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            from utils.pjsk.client import PJSKError, get_pjsk_client

            try:
                client = get_pjsk_client(self.region)
                profile = await client.get_profile(self.pjsk_user_id)
            except PJSKError as exc:
                await interaction.followup.send(f"Không thể kiểm tra hồ sơ: {exc}", ephemeral=True)
                return

            if self.verify_code not in profile.bio:
                safe_bio = _safe_inline_code(profile.bio or "(trống)")
                embed = discord.Embed(
                    title="Chưa tìm thấy mã xác minh trong Bio",
                    description=(
                        f"Mình chưa thấy mã `{self.verify_code}` trong phần giới thiệu (Bio) "
                        f"của **{_safe_display_name(profile.name)}** (`{self.pjsk_user_id}`).\n\n"
                        f"**Bio hiện tại:** `{safe_bio}`\n\n"
                        "Hãy lưu Bio trong game, đợi vài giây rồi bấm **Xác minh Bio** lại nhé."
                    ),
                    color=discord.Color.orange(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            existing_owner = await database.get_pjsk_link_by_game_id(self.region, self.pjsk_user_id)
            if existing_owner and existing_owner["discord_id"] != self.discord_id:
                self._done = True
                self._disable_all()
                self.stop()
                await interaction.edit_original_response(view=self)
                await interaction.followup.send(
                    f"Tài khoản PJSK `{self.pjsk_user_id}` ({self.region.upper()}) đã được liên kết với một tài khoản Discord khác.",
                    ephemeral=True,
                )
                return

            try:
                await database.set_pjsk_link(
                    self.discord_id,
                    self.region,
                    self.pjsk_user_id,
                    profile.name or self.initial_name,
                    time.time(),
                )
            except sqlite3.IntegrityError:
                self._done = True
                self._disable_all()
                self.stop()
                await interaction.edit_original_response(view=self)
                await interaction.followup.send(
                    f"Tài khoản PJSK `{self.pjsk_user_id}` ({self.region.upper()}) vừa được liên kết với một tài khoản Discord khác.",
                    ephemeral=True,
                )
                return

            self._done = True
            self._disable_all()
            self.stop()
            done_embed = discord.Embed(
                title=f"Liên kết thành công ({self.region.upper()})",
                description=(
                    f"Đã liên kết tài khoản PJSK **{_safe_display_name(profile.name)}** "
                    f"(Rank **{profile.rank}**, ID: `{self.pjsk_user_id}`) với tài khoản Discord của bạn!\n\n"
                    "Bạn có thể xóa mã xác minh khỏi Bio ngay bây giờ.\n"
                    f"Tiếp theo, dùng `/pjsk sync region:{self.region}` để đồng bộ bài FC/AP và xem `/b30`."
                ),
                color=discord.Color.green(),
            )
            await interaction.edit_original_response(embed=done_embed, view=self)

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                "Chỉ người gọi lệnh mới có thể bấm nút này.", ephemeral=True
            )
            return
        if self._done:
            await interaction.response.send_message("Phiên xác minh đã kết thúc.", ephemeral=True)
            return
        self._done = True
        self._disable_all()
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Đã hủy liên kết",
                description="Quá trình liên kết tài khoản đã bị hủy.",
                color=discord.Color.red(),
            ),
            view=self,
        )


class LinkUserIDModal(discord.ui.Modal):
    """Modal asking the player for their numeric PJSK User ID."""

    def __init__(self, region: str):
        super().__init__(title=f"Liên kết tài khoản PJSK ({region.upper()})")
        self.region = region
        self.user_id_input = discord.ui.TextInput(
            label="PJSK User ID (Player ID)",
            placeholder="Nhập dãy số Player ID trong mục Profile của game",
            required=True,
            min_length=5,
            max_length=19,
        )
        self.add_item(self.user_id_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_id = self.user_id_input.value.strip()
        if not (raw_id.isascii() and raw_id.isdigit()):
            await interaction.response.send_message(
                "Player ID phải là một dãy chữ số hợp lệ.", ephemeral=True
            )
            return

        pjsk_user_id = int(raw_id)
        if not (0 < pjsk_user_id <= _MAX_INT64):
            await interaction.response.send_message(
                "Player ID vượt quá phạm vi số nguyên hợp lệ.", ephemeral=True
            )
            return

        existing_owner = await database.get_pjsk_link_by_game_id(self.region, pjsk_user_id)
        if existing_owner and existing_owner["discord_id"] != interaction.user.id:
            await interaction.response.send_message(
                f"Tài khoản PJSK `{pjsk_user_id}` ({self.region.upper()}) đã được liên kết với một người dùng Discord khác.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        from utils.pjsk.client import PJSKError, get_pjsk_client

        try:
            client = get_pjsk_client(self.region)
            profile = await client.get_profile(pjsk_user_id)
        except PJSKError as exc:
            await interaction.followup.send(f"Không thể tìm thấy hồ sơ: {exc}", ephemeral=True)
            return

        code = _generate_verify_code()
        embed = discord.Embed(
            title=f"Xác minh chủ sở hữu tài khoản ({self.region.upper()})",
            description=(
                f"**Tên trong game:** `{_safe_inline_code(profile.name)}` (Rank **{profile.rank}**)\n"
                f"**User ID:** `{profile.user_id}`\n\n"
                f"1. Mở game → **Profile** → dán mã sau vào phần **Bio (Comment)**:\n"
                f"   `{code}`\n"
                "2. Lưu lại rồi bấm nút **Xác minh Bio** bên dưới (có hiệu lực 5 phút)."
            ),
            color=discord.Color.blurple(),
        )
        view = LinkVerifyView(
            discord_id=interaction.user.id,
            region=self.region,
            pjsk_user_id=profile.user_id,
            verify_code=code,
            initial_name=profile.name,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# ── Views & Modals for Transfer-ID Sync ───────────────────────────────────────


class TransferConfirmView(discord.ui.View):
    """DM confirmation view before executing a destructive one-time Transfer ID login."""

    def __init__(
        self,
        *,
        discord_id: int,
        region: str,
        pjsk_user_id: int,
        transfer_id: str,
        transfer_password: str,
        timeout: float = 60.0,
    ):
        super().__init__(timeout=timeout)
        self.discord_id = discord_id
        self.region = region
        self.pjsk_user_id = pjsk_user_id
        self.transfer_id = transfer_id
        self.transfer_password = transfer_password
        self.message: discord.Message | None = None
        self._handled = False

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    def _clear_secrets(self) -> None:
        self.transfer_id = ""
        self.transfer_password = ""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                "Chỉ chủ tài khoản mới có thể xác nhận phiên transfer này.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self._handled:
            return
        self._handled = True
        self._disable_all()
        self._clear_secrets()
        self.stop()
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(
                    embed=discord.Embed(
                        title="Hết thời gian xác nhận",
                        description=(
                            "Quá trình đồng bộ đã tự hủy vì quá 60 giây.\n"
                            "Transfer ID cũ của bạn **chưa bị sử dụng** — để an toàn, hãy tạo lại Transfer ID mới trong game."
                        ),
                        color=discord.Color.orange(),
                    ),
                    view=self,
                )

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                "Chỉ chủ tài khoản mới có thể hủy phiên này.", ephemeral=True
            )
            return
        if self._handled:
            await interaction.response.send_message(
                "Phiên xác nhận này đã kết thúc.", ephemeral=True
            )
            return
        self._handled = True
        self._disable_all()
        self._clear_secrets()
        self.stop()
        embed = discord.Embed(
            title="Đã hủy chuyển tài khoản",
            description=(
                "Quá trình đồng bộ đã bị hủy. Transfer ID cũ của bạn **chưa bị tiêu thụ**.\n"
                "-# Để an toàn, bạn nên đổi lại cài đặt Account Transfer trong game."
            ),
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Xác nhận Transfer & Đồng bộ", style=discord.ButtonStyle.success)
    async def transfer_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                "Chỉ chủ tài khoản mới có thể xác nhận phiên này.", ephemeral=True
            )
            return
        if self._handled:
            await interaction.response.send_message(
                "Phiên xác nhận này đang được xử lý hoặc đã hoàn tất.", ephemeral=True
            )
            return

        op_lock = _get_transfer_lock(self.discord_id, self.region)
        if op_lock.locked():
            await interaction.response.send_message(
                f"Đang có một phiên sync/recover khác chạy cho server **{self.region.upper()}**. "
                "Vui lòng đợi phiên đó hoàn tất trước nhé.",
                ephemeral=True,
            )
            return

        # Mark handled & stop the view BEFORE any await so on_timeout() can NEVER overwrite the DM!
        self._handled = True
        self._disable_all()
        self.stop()
        tid, tpw = self.transfer_id, self.transfer_password
        self._clear_secrets()

        async with op_lock:
            progress_embed = discord.Embed(
                title="Đang đăng nhập & đồng bộ dữ liệu...",
                description=(
                    "Bot đang đăng nhập để lấy dữ liệu FC/AP và tạo **Transfer ID mới** trả lại cho bạn.\n\n"
                    "Nếu tin nhắn này không cập nhật sau 1 phút, hãy dùng lệnh "
                    f"`/pjsk recover region:{self.region}` hoặc đăng nhập lại bằng Game Center / Google Play.\n\n"
                    f"**Transfer ID cũ:** `{tid}`\n"
                    f"**Mật khẩu cũ:** `{tpw}`"
                ),
                color=discord.Color.dark_gray(),
            )
            await interaction.response.edit_message(embed=progress_embed, view=self)

            from utils.pjsk.client import PJSKError, PJSKSyncPartialError, get_pjsk_client

            client = get_pjsk_client(self.region)

            async def _save_recovery(uid: int, cred: str) -> None:
                await database.save_pjsk_recovery(
                    self.discord_id, self.region, uid, cred, time.time()
                )

            try:
                result = await client.execute_transfer_and_sync(
                    tid,
                    tpw,
                    on_credential_acquired=_save_recovery,
                )
            except PJSKSyncPartialError as partial:
                warn_embed = discord.Embed(
                    title="Đã tạo Transfer ID mới (lỗi tải dữ liệu bài hát)",
                    description=(
                        "Bot đã đăng nhập và tạo thành công **Transfer ID mới** cho bạn, nhưng bước tải danh sách bài hát bị lỗi.\n"
                        "Hãy dùng thông tin bên dưới để đăng nhập lại vào game ngay:\n\n"
                        f"**Transfer ID mới:** `{partial.new_transfer_id}`\n"
                        f"**Mật khẩu mới:** `{partial.new_password}`\n\n"
                        f"-# Chi tiết lỗi: {partial}"
                    ),
                    color=discord.Color.orange(),
                )
                delivered = await _deliver_dm_embed(
                    embed=warn_embed,
                    interaction=interaction,
                    message=self.message,
                    user=interaction.user,
                    view=self,
                )
                if delivered:
                    await database.delete_pjsk_recovery(self.discord_id, self.region)
                return
            except PJSKError as exc:
                err_embed = discord.Embed(
                    title="Đồng bộ thất bại!",
                    description=(
                        f"Lỗi: {exc}\n\n"
                        "Nếu tài khoản của bạn đã bị đăng xuất khỏi thiết bị, hãy chạy ngay "
                        f"`/pjsk recover region:{self.region}` để bot cấp lại Transfer ID mới, "
                        "hoặc đăng nhập lại bằng Game Center / Google Play.\n\n"
                        f"**Transfer ID cũ:** `{tid}`\n"
                        f"**Mật khẩu cũ:** `{tpw}`"
                    ),
                    color=discord.Color.red(),
                )
                await _deliver_dm_embed(
                    embed=err_embed,
                    interaction=interaction,
                    message=self.message,
                    user=interaction.user,
                    view=self,
                )
                return
            except Exception as exc:
                logger.exception("Unexpected error during PJSK transfer sync: %s", exc)
                err_embed = discord.Embed(
                    title="Đã xảy ra lỗi ngoài ý muốn!",
                    description=(
                        "Nếu bạn bị đăng xuất khỏi game, hãy chạy ngay "
                        f"`/pjsk recover region:{self.region}` để cấp lại Transfer ID mới, "
                        "hoặc đăng nhập lại bằng Game Center / Google Play."
                    ),
                    color=discord.Color.red(),
                )
                await _deliver_dm_embed(
                    embed=err_embed,
                    interaction=interaction,
                    message=self.message,
                    user=interaction.user,
                    view=self,
                )
                return

            # Save clears in try/except so a transient DB error NEVER prevents delivering the new Transfer ID!
            db_save_note = ""
            try:
                await database.replace_pjsk_clears(
                    self.discord_id,
                    self.region,
                    result.clears,
                    pjsk_name=result.name,
                    synced_at=time.time(),
                )
            except Exception as db_exc:
                logger.exception("Failed to save PJSK clears after transfer: %s", db_exc)
                db_save_note = (
                    "\n\n⚠️ *Lưu ý: Đã tạo Transfer ID mới thành công nhưng bước lưu bài hát vào DB bị lỗi; "
                    "hãy vào lại game trước rồi thử sync lại sau.*"
                )

            ap_total = sum(1 for st in result.clears.values() if st == "ap")
            fc_total = sum(1 for st in result.clears.values() if st == "fc")

            success_embed = discord.Embed(
                title=f"Đồng bộ thành công! ({self.region.upper()})",
                description=(
                    f"Đã cập nhật dữ liệu của **{_safe_display_name(result.name)}** (Rank **{result.rank}**): "
                    f"**{ap_total}** AP · **{fc_total}** FC (từ {result.total_musics} bài hát).\n\n"
                    "**Dùng Transfer ID mới bên dưới để lấy lại tài khoản trong game:**\n"
                    "-# Title Screen → Menu → Account Transfer → Transfer to Different OS\n\n"
                    f"**Transfer ID mới:** `{result.new_transfer_id}`\n"
                    f"**Mật khẩu mới:** `{result.new_password}`\n\n"
                    "Hoặc bạn có thể đăng nhập lại bằng **Game Center** / **Google Play**.\n"
                    "**Sau khi vào lại game, hãy tạo lại Transfer ID mới để bảo mật tài khoản.**\n\n"
                    f"Dùng `/b30 region:{self.region}` để xem bảng B30 của bạn!"
                    f"{db_save_note}"
                ),
                color=discord.Color.green(),
            )
            success_embed.set_footer(text=f"{self.region.upper()} · Dữ liệu đã được lưu")
            delivered = await _deliver_dm_embed(
                embed=success_embed,
                interaction=interaction,
                message=self.message,
                user=interaction.user,
                view=self,
            )
            # Only wipe crash-recovery credential AFTER the DM containing the new Transfer ID succeeded!
            if delivered:
                await database.delete_pjsk_recovery(self.discord_id, self.region)


class TransferIDModal(discord.ui.Modal):
    """Modal collecting Transfer ID (16 chars) + Password (8-16 chars) before moving to DM."""

    def __init__(self, *, region: str, pjsk_user_id: int):
        super().__init__(title=f"Đồng bộ PJSK ({region.upper()}) qua Transfer ID")
        self.region = region
        self.pjsk_user_id = pjsk_user_id

        self.transfer_id = discord.ui.TextInput(
            label="Transfer ID (16 ký tự)",
            placeholder="Menu > Account Transfer > Transfer to Different OS",
            required=True,
            min_length=16,
            max_length=24,  # allow surrounding spaces when copy-pasting; stripped & validated below
        )
        self.transfer_password = discord.ui.TextInput(
            label="Mật khẩu Transfer (8–16 ký tự)",
            placeholder="Mật khẩu bạn vừa đặt trong game",
            required=True,
            min_length=8,
            max_length=16,
        )
        self.add_item(self.transfer_id)
        self.add_item(self.transfer_password)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=discord.Embed(
                description="Đang mở tin nhắn riêng (DM) với bạn...",
                color=discord.Color.blurple(),
            ),
            ephemeral=True,
        )
        try:
            dm_msg = await interaction.user.send(
                embed=discord.Embed(
                    description=f"Đang kiểm tra Transfer ID trên server **{self.region.upper()}**...",
                    color=discord.Color.blurple(),
                )
            )
            await interaction.edit_original_response(
                embed=discord.Embed(
                    description="Đã mở DM thành công! Hãy kiểm tra tin nhắn riêng để tiếp tục.",
                    color=discord.Color.green(),
                )
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="Không thể gửi DM cho bạn",
                    description=(
                        "Bot bắt buộc gửi Transfer ID mới qua **DM** để bảo mật và tránh mất mã.\n"
                        "Hãy bật **Cho phép nhận tin nhắn trực tiếp từ thành viên server** rồi thử lại."
                    ),
                    color=discord.Color.red(),
                )
            )
            return

        from utils.pjsk.client import PJSKError, get_pjsk_client

        tid = self.transfer_id.value.strip()
        tpw = self.transfer_password.value
        try:
            client = get_pjsk_client(self.region)
            preview = await client.preview_transfer(tid, tpw)
        except PJSKError as exc:
            await dm_msg.edit(
                embed=discord.Embed(
                    title="Không thể xác thực Transfer ID",
                    description=str(exc),
                    color=discord.Color.red(),
                )
            )
            return
        except Exception as exc:
            logger.exception("Unexpected error during Transfer ID preview: %s", exc)
            await dm_msg.edit(
                embed=discord.Embed(
                    title="Lỗi kiểm tra Transfer ID",
                    description="Đã xảy ra lỗi không mong muốn khi kiểm tra Transfer ID. Vui lòng thử lại sau.",
                    color=discord.Color.red(),
                )
            )
            return

        if preview.user_id != self.pjsk_user_id:
            await dm_msg.edit(
                embed=discord.Embed(
                    title="Tài khoản không khớp!",
                    description=(
                        f"Transfer ID này thuộc về ID `{preview.user_id}` (**{_safe_display_name(preview.name)}**), "
                        f"không khớp với tài khoản `{self.pjsk_user_id}` bạn đã liên kết.\n"
                        "Quá trình đã bị hủy — Transfer ID chưa bị sử dụng."
                    ),
                    color=discord.Color.red(),
                )
            )
            return

        if preview.is_restricted:
            await dm_msg.edit(
                embed=discord.Embed(
                    title="Tài khoản đang bị giới hạn Transfer (Top 300 Event)",
                    description=(
                        "Tài khoản của bạn hiện đang có giới hạn chuyển thiết bị trong sự kiện (t300).\n"
                        "Bot từ chối đăng nhập để bảo vệ lượt transfer của bạn!"
                    ),
                    color=discord.Color.red(),
                )
            )
            return

        created_tag = _pjsk_created_timestamp_tag(preview.user_id)
        confirm_embed = discord.Embed(
            title=f"Xác nhận Transfer ({self.region.upper()})",
            description=(
                "Sau khi đồng bộ xong, bot sẽ gửi lại **Transfer ID & Mật khẩu mới** ngay trong DM này "
                "để bạn đăng nhập lại vào game.\n"
                "-# Khuyến nghị liên kết sẵn **Game Center** hoặc **Google Play** để đảm bảo an toàn tuyệt đối.\n\n"
                f"**User ID:** `{preview.user_id}`\n"
                f"**Tên:** `{_safe_inline_code(preview.name)}`\n"
                f"**Rank:** **🎵 {preview.rank}**\n"
                f"**Ngày tạo:** {created_tag}"
            ),
            color=discord.Color.dark_magenta(),
        )
        confirm_embed.set_footer(text=f"{self.region.upper()} · Xác nhận trong vòng 60 giây")
        view = TransferConfirmView(
            discord_id=interaction.user.id,
            region=self.region,
            pjsk_user_id=self.pjsk_user_id,
            transfer_id=tid,
            transfer_password=tpw,
        )
        view.message = dm_msg
        await dm_msg.edit(embed=confirm_embed, view=view)


def _parse_suite_upload_sync(
    raw_bytes: bytes,
) -> tuple[dict[tuple[int, str], str], int | None, str | None]:
    """Decode & extract clears from an uploaded suite.json off the asyncio event loop."""
    from utils.pjsk.constants import extract_music_clears

    suite = json.loads(raw_bytes.decode("utf-8-sig"))
    if not isinstance(suite, dict) or "userMusics" not in suite:
        raise ValueError("File không chứa trường `userMusics`.")
    gamedata = suite.get("userGamedata") if isinstance(suite.get("userGamedata"), dict) else {}
    raw_uid = gamedata.get("userId")
    file_uid: int | None = None
    if raw_uid is not None:
        try:
            file_uid = int(raw_uid)
        except (TypeError, ValueError) as exc:
            raise ValueError("Trường `userGamedata.userId` không phải số nguyên hợp lệ.") from exc
    name = str(gamedata.get("name") or "").strip() or None
    clears = extract_music_clears(suite)
    return clears, file_uid, name


# ── Main Cog ──────────────────────────────────────────────────────────────────


class PJSKCog(commands.Cog):
    """Project Sekai account link, Transfer-ID sync, profile & Best 30 rating."""

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
            who = "Bạn" if target.id == interaction.user.id else f"**{target.display_name}**"
            await interaction.response.send_message(
                f"{who} chưa liên kết tài khoản PJSK **{reg.upper()}**. Dùng `/pjsk link region:{reg}` để liên kết.",
                ephemeral=True,
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

        embed = discord.Embed(
            title=f"{profile.name}  [{reg.upper()}]",
            description=profile.bio or "*Không có Bio*",
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
                        "(secret dùng để ký header `x-inherit-id-verify-token` khi đăng nhập Transfer ID).\n\n"
                        f"Trong lúc chờ cấu hình `{env_name}`, bạn vẫn có thể nhập dữ liệu bằng lệnh "
                        f"`/pjsk import region:{reg}` với file `suite.json`."
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
        op_lock = _get_transfer_lock(interaction.user.id, reg)
        if op_lock.locked():
            await interaction.response.send_message(
                f"Đang có một phiên sync/recover khác chạy cho server **{reg.upper()}**. Vui lòng đợi hoàn tất.",
                ephemeral=True,
            )
            return

        async with op_lock:
            rec = await database.get_pjsk_recovery(interaction.user.id, reg)
            if not rec:
                await interaction.response.send_message(
                    f"Không có phiên transfer nào đang chờ khôi phục cho server **{reg.upper()}**.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                "Đang gửi Transfer ID khôi phục qua DM cho bạn...", ephemeral=True
            )
            try:
                dm_msg = await interaction.user.send(
                    f"Đang tạo lại Transfer ID khôi phục cho server **{reg.upper()}**..."
                )
            except discord.Forbidden:
                await interaction.edit_original_response(
                    content="Không thể gửi DM cho bạn. Hãy bật nhận DM rồi thử lại `/pjsk recover`."
                )
                return

            from utils.pjsk.client import PJSKError, get_pjsk_client

            try:
                client = get_pjsk_client(reg)
                new_tid, new_pw = await client.reissue_transfer_from_credential(
                    rec["pjsk_user_id"], rec["credential"]
                )
            except PJSKError as exc:
                await dm_msg.edit(content=f"Khôi phục thất bại: {exc}")
                return
            except Exception as exc:
                logger.exception("Unexpected error during /pjsk recover: %s", exc)
                await dm_msg.edit(
                    content="Khôi phục gặp lỗi không mong muốn. Vui lòng thử lại sau ít phút."
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
            delivered = await _deliver_dm_embed(
                embed=rec_embed,
                message=dm_msg,
                user=interaction.user,
            )
            if delivered:
                await database.delete_pjsk_recovery(interaction.user.id, reg)

    @pjsk_group.command(
        name="import",
        description="Nhập dữ liệu FC/AP từ file suite.json (thay thế hoặc bổ sung cho Transfer ID)",
    )
    @app_commands.describe(
        region="Chọn server (EN hoặc JP)",
        suite_file="File suite.json xuất từ game/Haruki/sssekai",
    )
    @app_commands.choices(region=REGION_CHOICES)
    async def pjsk_import(
        self,
        interaction: discord.Interaction,
        region: str,
        suite_file: discord.Attachment,
    ) -> None:
        reg = region.lower()
        link = await database.get_pjsk_link(interaction.user.id, reg)
        if not link:
            await interaction.response.send_message(
                f"Bạn cần liên kết tài khoản PJSK **{reg.upper()}** trước bằng `/pjsk link region:{reg}`.",
                ephemeral=True,
            )
            return

        if suite_file.size > _MAX_SUITE_UPLOAD_BYTES:
            await interaction.response.send_message("File quá lớn (tối đa 15 MB).", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            raw_bytes = await suite_file.read()
            clears, file_uid, parsed_name = await asyncio.to_thread(
                _parse_suite_upload_sync, raw_bytes
            )
        except Exception as exc:
            await interaction.followup.send(f"File JSON không hợp lệ: {exc}", ephemeral=True)
            return

        if file_uid is not None and file_uid != link["pjsk_user_id"]:
            await interaction.followup.send(
                f"User ID trong file (`{file_uid}`) không khớp với tài khoản đã liên kết (`{link['pjsk_user_id']}`).",
                ephemeral=True,
            )
            return

        name = parsed_name or link.get("pjsk_name") or "Player"
        await database.replace_pjsk_clears(
            interaction.user.id, reg, clears, pjsk_name=name, synced_at=time.time()
        )
        ap_total = sum(1 for st in clears.values() if st == "ap")
        fc_total = sum(1 for st in clears.values() if st == "fc")
        await interaction.followup.send(
            f"Đã nhập thành công dữ liệu **{_safe_display_name(name)}** ({reg.upper()}): "
            f"**{ap_total}** AP · **{fc_total}** FC.\n"
            f"Dùng `/b30 region:{reg}` để xem bảng B30!",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

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
            who = "Bạn" if target.id == interaction.user.id else f"**{target.display_name}**"
            await interaction.response.send_message(
                f"{who} chưa liên kết tài khoản PJSK **{reg.upper()}**. Dùng `/pjsk link region:{reg}` trước nhé.",
                ephemeral=True,
            )
            return

        clears = await database.get_pjsk_clears(target.id, reg)
        if not clears:
            who = "Bạn" if target.id == interaction.user.id else f"**{target.display_name}**"
            await interaction.response.send_message(
                f"{who} chưa có dữ liệu bài hát cho **{reg.upper()}**. "
                f"Hãy dùng `/pjsk sync region:{reg}` (hoặc `/pjsk import region:{reg}`) để cập nhật trước nhé.",
                ephemeral=True,
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
            f"**{_safe_display_name(raw_name)}** (`{reg.upper()}`) — **B30 Rating: {summary.ranking:.2f}** "
            f"({len(summary.entries)}/30 charts: **{summary.ap_count}** AP · **{summary.fc_count}** FC)"
            f"{sync_note}"
        )
        await interaction.followup.send(
            content=caption,
            file=discord.File(img_bytes, filename=f"b30_{reg}_{link['pjsk_user_id']}.jpg"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @pjsk_group.command(name="b30", description="Xem bảng Best 30 (B30) rating Project Sekai")
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

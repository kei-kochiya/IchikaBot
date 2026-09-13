import discord

# ── Constants ──────────────────────────────────────────────────────────────────
GUESS_PREFIX = "-g "
TOTAL_ROUNDS = 5
PHASE_TIMEOUT = 20  # seconds per phase
PHASE_WRONG_MAX = 4  # total wrong guesses (any player) before advancing

CROP_BASE = 400  # base crop size (also phase 3)
CROP_P2 = 300  # phase 2 crop (colour, centred in base)
CROP_P1 = 250  # phase 1 crop (grayscale, centred in base)

PHASE_POINTS = {1: 3, 2: 2, 3: 1}

PHASE_META = {
    1: ("Giai đoạn 1", f"{CROP_P1}×{CROP_P1} đen trắng", discord.Color.dark_gray()),
    2: ("Giai đoạn 2", f"{CROP_P2}×{CROP_P2} màu", discord.Color.gold()),
    3: ("Giai đoạn 3", f"{CROP_BASE}×{CROP_BASE} màu", discord.Color.green()),
}


def _scores_preview(scores: dict) -> str:
    if not scores:
        return ""
    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
    return "  ".join(f"<@{uid}>:{pts}" for uid, pts in top)


def create_start_embed() -> discord.Embed:
    return discord.Embed(
        title="🏆 Card Guessing Tournament!",
        description=(
            f"**{TOTAL_ROUNDS} vòng** — bắt đầu sau **5 giây**!\n\n"
            f"Gõ `{GUESS_PREFIX.strip()} [tên nhân vật]` để đoán.\n\n"
            f"**Điểm thưởng mỗi vòng:**\n"
            f"⬛ Giai đoạn 1 — {CROP_P1}×{CROP_P1} đen trắng → **3 điểm**\n"
            f"🟨 Giai đoạn 2 — {CROP_P2}×{CROP_P2} màu → **2 điểm**\n"
            f"🟩 Giai đoạn 3 — {CROP_BASE}×{CROP_BASE} màu → **1 điểm**"
        ),
        color=discord.Color.gold(),
    ).set_footer(text=f"Mỗi giai đoạn: {PHASE_TIMEOUT}s | {PHASE_WRONG_MAX} lần đoán sai toàn kênh")


def create_round_embed(round_num: int, phase_num: int, scores: dict, fname: str) -> discord.Embed:
    label, size_text, color = PHASE_META[phase_num]
    embed = discord.Embed(
        title=f"Tournament — Vòng {round_num}/{TOTAL_ROUNDS}",
        description=(
            f"{label} | {size_text}\n"
            f"Gõ `{GUESS_PREFIX.strip()} [tên]` để đoán!\n\n"
            f"*{PHASE_TIMEOUT}s · tối đa {PHASE_WRONG_MAX} lần sai toàn kênh*"
        ),
        color=color,
    )
    embed.set_image(url=f"attachment://{fname}")

    scores_line = _scores_preview(scores)
    if scores_line:
        embed.set_footer(text=f"Điểm: {scores_line}")
    return embed


def create_result_embed(
    winner: discord.User | discord.Member | None,
    pts: int,
    full_name: str,
    card_prefix: str,
    round_num: int,
) -> discord.Embed:
    if winner:
        result_embed = discord.Embed(
            title=f"{winner.display_name} đoán đúng! +{pts} điểm",
            description=f"Đáp án: **{full_name}**\n*{card_prefix}*",
            color=discord.Color.green(),
        )
    else:
        result_embed = discord.Embed(
            title="Hết thời gian & lượt đoán!",
            description=f"Đáp án: **{full_name}**\n*{card_prefix}*",
            color=discord.Color.red(),
        )
    result_embed.set_footer(text=f"Vòng {round_num}/{TOTAL_ROUNDS}")
    return result_embed


def create_leaderboard_embed(scores: dict) -> discord.Embed:
    medals = ["🥇", "🥈", "🥉"]
    embed = discord.Embed(title="🏆 Kết Quả Tournament", color=discord.Color.gold())

    if not scores:
        embed.description = "Không ai đoán được câu nào!"
    else:
        lines = []
        for i, (uid, pts) in enumerate(sorted(scores.items(), key=lambda x: x[1], reverse=True)):
            medal = medals[i] if i < 3 else f"**#{i + 1}**"
            lines.append(f"{medal} <@{uid}> — **{pts} điểm**")
        embed.description = "\n".join(lines)

    embed.set_footer(text="Giai đoạn 1 = 3đ  |  Giai đoạn 2 = 2đ  |  Giai đoạn 3 = 1đ")
    return embed

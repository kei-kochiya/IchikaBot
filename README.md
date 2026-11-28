<div align="center">

# IchikaBot

**Discord bot tiếng Việt cho *Project Sekai: Colorful Stage!***<br/>
Tra cứu dữ liệu game · Giả lập Gacha · 4 Minigame đoán bài & chart · Liên kết PJSK & Best 30

[![Mời bot vào Discord](https://img.shields.io/badge/Discord-Mời_IchikaBot-33AAEE?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/oauth2/authorize?client_id=1416351312039383051&permissions=2150746176&integration_type=0&scope=bot%20applications.commands)
[![CI](https://img.shields.io/github/actions/workflow/status/kei-kochiya/IchikaBot/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/kei-kochiya/IchikaBot/actions)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-4455DD?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

[Tính năng](#tính-năng) · [Danh sách lệnh](#danh-sách-lệnh) · [Tự host](#tự-host) · [Kiến trúc](docs/vi/ARCHITECT.md) · [English](docs/en/README.md)

</div>

---

## Tính năng

| Nhóm | Chi tiết |
|---|---|
| **Tra cứu** | Card (untrained / trained), thông tin nhân vật, bài hát (độ khó, số nốt, tác giả), sự kiện từ Sekai-World. |
| **Giả lập Gacha** | Quay 1 hoặc 10 lượt (`6%` 4★ · `15%` 3★ · `79%` 2★; lượt 10 đảm bảo ≥ 3★; bảo hiểm 4★ ở mốc 50 pity). |
| **4 Minigame đoán đáp án** | Gõ <kbd>-g &lt;đáp án&gt;</kbd> để đoán nhân vật qua thẻ (`/guess`), đoán bài qua ảnh bìa (`/jacketguess`), đoán bài qua đoạn chart **Master / Append** (`/chartguess`), hoặc đoán nhạc 20s trong voice (`/songguess`). |
| **Tài khoản PJSK & B30** | Liên kết EN/JP qua Bio (`/pjsk link`), đồng bộ FC/AP bằng Transfer ID (`/pjsk sync`, khôi phục với `/pjsk recover`), render ảnh Best 30 `pjskb30` (`/b30`). |
| **Tự động hóa & Tiện ích** | Chúc mừng sinh nhật nhân vật lúc `00:00 JST`, Card of the Day định kỳ `0.5–24h`, tra cứu Mercari Nhật (quy đổi VND) và giá xăng dầu PVOIL. |

---

## Danh sách lệnh

Bot dùng **Slash Commands (`/`)**. Gõ `/help` hoặc `/help <danh mục>` trong Discord để tra cứu.

<details open>
<summary><strong>Tra cứu &amp; Gacha</strong></summary>

| Lệnh | Chức năng |
|---|---|
| `/card <name>` | Tra cứu thẻ theo tên hoặc ID (có nút chuyển ảnh thường / sau nâng cấp) |
| `/profile info <name>` | Xem hồ sơ chi tiết nhân vật |
| `/song search <query>` | Tìm kiếm bài hát (JP / EN / Romaji) |
| `/song info <name>` | Xem thông tin bài hát và cấp độ / số nốt mọi độ khó |
| `/song random` | Chọn ngẫu nhiên một bài hát (lọc được theo cấp độ) |
| `/event current` | Sự kiện đang diễn ra hoặc sắp tới |
| `/event history` | Lịch sử các sự kiện đã kết thúc |
| `/event search <name>` | Tìm kiếm sự kiện theo tên |
| `/gacha pull [amount]` | Quay 1 hoặc 10 thẻ |
| `/gacha pity` | Kiểm tra số pity hiện tại của bạn |

</details>

<details open>
<summary><strong>Minigame</strong></summary>

| Lệnh | Chức năng |
|---|---|
| `/guess [mode]` | Đoán nhân vật qua ảnh thẻ (`easy` / `normal` / `hard`) |
| `/guessmode [mode]` | Xem hoặc đặt độ khó mặc định cho `/guess` |
| `/jacketguess [mode]` | Đoán tên bài hát qua ảnh bìa jacket bị cắt / hiệu ứng |
| `/chartguess [difficulty] [mode]` | Đoán tên bài hát qua đoạn chart `master` hoặc `append` |
| `/songguess [mode] [pool]` | Đoán nhạc 20s trong kênh voice (Commission hoặc Tất cả; có chế độ hiệu ứng) |

</details>

<details>
<summary><strong>Tài khoản &amp; Best 30</strong></summary>

| Lệnh | Chức năng |
|---|---|
| `/pjsk link [region]` | Liên kết tài khoản PJSK (EN/JP) bằng mã xác minh trong Bio |
| `/pjsk profile [region] [user]` | Xem hồ sơ PJSK đã liên kết |
| `/pjsk sync [region]` | Đồng bộ FC/AP qua Transfer ID trong DM và nhận ngay Transfer ID mới |
| `/pjsk recover [region]` | Cấp lại Transfer ID nếu quá trình sync bị gián đoạn |
| `/pjsk unlink [region]` | Hủy liên kết và xóa dữ liệu đã lưu |
| `/b30 [region] [user]` | Render ảnh bảng xếp hạng Best 30 (hoặc `/pjsk b30`) |

</details>

<details>
<summary><strong>Sinh nhật, Tự động hóa &amp; Tiện ích</strong></summary>

| Lệnh | Chức năng |
|---|---|
| `/birthday check` | Sinh nhật hôm nay và sắp tới |
| `/birthday countdown [name]` | Đếm ngược ngày sinh nhật kèm ảnh thẻ |
| `/cotd status` | Xem trạng thái Card of the Day của server |
| `/mercari <link hoặc ID>` | Tra cứu sản phẩm Mercari Nhật kèm ước tính giá VND |
| `/gasprice` | Xem giá xăng dầu PVOIL hôm nay |

> **Lệnh quản trị server:** `/birthday channel`, `/birthday disable`, `/cotd channel`, `/cotd interval`, `/cotd now`, `/cotd disable` yêu cầu quyền **Manage Server**. `/update_data` yêu cầu quyền **Administrator**.

</details>

---

## Tự host

### 1. Yêu cầu môi trường

- **Python 3.11+**
- **FFmpeg** trong `PATH` (cho `/songguess`; trên Linux cài thêm `libopus`)
- **Discord Bot Token** đã bật **Message Content Intent** trong Developer Portal (để nhận câu trả lời `-g` trong minigame). Quyền cần cấp: `Send Messages`, `Embed Links`, `Attach Files`, `Add Reactions`, `Read Message History`, `Use Application Commands`, cùng `Connect` & `Speak` cho voice.

### 2. Cài đặt và khởi chạy

```bash
git clone https://github.com/kei-kochiya/IchikaBot.git
cd IchikaBot
pip install -r requirements.txt
cp .env.example .env
# Điền DISCORD_TOKEN vào .env
python bot.py
```

Slash commands tự đồng bộ khi khởi động (chủ bot có thể ép đồng bộ lại bằng `@IchikaBot sync`). Lần chạy đầu mất khoảng 1 phút để tải dữ liệu game (~70 MB).

### 3. Biến môi trường (`.env`)

| Biến | Bắt buộc | Mô tả |
|---|---|---|
| `DISCORD_TOKEN` | Có | Token của Discord bot |
| `LOG_LEVEL` | Không | `DEBUG`, `INFO` (mặc định), `WARNING`, `ERROR` |
| `PJSK_EN_INHERIT_TOKEN` | Không | JWT secret ký `x-inherit-id-verify-token` cho `/pjsk sync` server EN |
| `PJSK_JP_INHERIT_TOKEN` | Không | JWT secret ký `x-inherit-id-verify-token` cho `/pjsk sync` server JP |

> [!IMPORTANT]
> Hai JWT secret (`PJSK_EN_INHERIT_TOKEN`, `PJSK_JP_INHERIT_TOKEN`) **không có sẵn trong repository**. Nếu muốn bật `/pjsk sync` khi tự host, bạn phải **tự tìm và cấu hình** trong `.env`. Khi chưa cấu hình, toàn bộ các tính năng khác, gồm cả `/pjsk link` và `/pjsk profile`, vẫn chạy bình thường.

<details>
<summary><strong>Thư mục dữ liệu cục bộ &amp; chuyển máy chủ</strong></summary>

| Đường dẫn | Nội dung | Nguồn |
|---|---|---|
| `gameData/static/` | Nhân vật, biệt danh, `song.xlsx` | Có sẵn trong repo (`git pull` để cập nhật) |
| `gameData/JP_data/`, `EN_data/` | Dữ liệu thẻ, bài hát, sự kiện | Tự tải ở lần chạy đầu, kiểm tra mỗi 6 giờ |
| `music/` | Audio cho `/songguess`, đặt tên theo ID (`54.mp3`) | Không có trong repo — tự bổ sung |
| `ichika.db` | SQLite lưu pity, cài đặt server, dữ liệu PJSK/B30 | Tự tạo khi chạy |
| `.assetcache/` | Cache ảnh thẻ, jacket, chart và hằng số B30 | Tự tạo lại khi cần; xóa an toàn |

**Chuyển sang máy chủ mới:** tắt bot rồi chép `.env`, `music/` và `ichika.db` (chép thêm `gameData/JP_data`, `gameData/EN_data` và `gameData/updaterState.json` để bỏ qua bước tải dữ liệu lần đầu).

</details>

---

## Phát triển & Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
ruff format --check .
```

Bộ test mặc định chạy hoàn toàn offline (`pytest -m live` để chạy các bài kiểm tra API thật). CI kiểm tra tự động trên Python 3.11–3.13 kèm `ruff` và `pip-audit`.

---

<div align="center">

<sub>✦ · · · ── ☆ ── · · · ✦</sub><br/>
<sub>Made with ♥ for the <strong>Project Sekai Vietnamese community</strong></sub>

</div>
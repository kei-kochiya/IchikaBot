# IchikaBot

[![English](https://img.shields.io/badge/Docs-English-blue)](docs/en/README.md) [![Kiến trúc (VI)](https://img.shields.io/badge/Kiến_trúc-Tiếng_Việt-green)](docs/vi/ARCHITECT.md) [![Architecture (EN)](https://img.shields.io/badge/Architecture-English-lightgrey)](docs/en/ARCHITECT.md)

Discord bot dành cho *Project Sekai: Colorful Stage!* — hỗ trợ tra cứu thẻ, bài hát, sự kiện, hồ sơ nhân vật, giả lập quay gacha, chơi 2 minigame đoán nhân vật & đoán nhạc trong voice, thông báo sinh nhật/Card of the Day tự động, và liên kết tài khoản PJSK (EN/JP) để tính bảng **Best 30 (B30)**. Bot phản hồi bằng tiếng Việt.

[Mời IchikaBot vào server Discord](https://discord.com/oauth2/authorize?client_id=1416351312039383051&permissions=2150746176&integration_type=0&scope=bot%20applications.commands)

## Tính năng

- **Tra cứu dữ liệu game.** Xem thẻ (có nút chuyển đổi ảnh thường / sau nâng cấp), hồ sơ nhân vật, bài hát (tác giả, ngày phát hành, cấp độ và số nốt của mọi độ khó) và sự kiện (đang diễn ra, lịch sử, tìm kiếm). Dữ liệu lấy từ kho master database của Sekai-World và tự động cập nhật định kỳ.
- **Giả lập quay Gacha.** Quay 1 hoặc 10 lần với tỉ lệ 6% cho 4★, 15% cho 3★ và 79% cho 2★. Thẻ thứ 10 của lượt quay 10 luôn từ 3★ trở lên, và đạt 50 lượt không ra 4★ sẽ bảo hiểm 4★. Pity được lưu riêng theo từng người dùng, ảnh kết quả dựng giống giao diện trong game.
- **Đoán nhân vật (`/guess`).** Nhìn một phần ảnh thẻ để đoán tên nhân vật với 3 độ khó: *Dễ* (crop đúng vùng nhân vật dựa trên ảnh cutout), *Thường* (crop ngẫu nhiên trên thẻ) và *Khó* (đen trắng, vỡ hạt, làm mờ hoặc đảo màu). Mỗi người dùng có thể đặt độ khó mặc định bằng `/guessmode` (mặc định là Dễ).
- **Đoán nhạc trong Voice (`/songguess`).** Bot vào kênh voice và phát đoạn nhạc 20 giây. Mặc định lấy các bài commissioned, hoặc chọn toàn bộ bài hát; chế độ khó phát nhanh hơn, chậm hơn hoặc phát ngược.
- **Thông báo tự động theo server.** Đăng bài chúc mừng lúc 00:00 JST vào sinh nhật mỗi nhân vật (và thẻ đếm ngược vào ngày thường), cùng tính năng gửi *Card of the Day* theo chu kỳ từ 0.5 đến 24 giờ.
- **Tài khoản PJSK & Bảng Best 30 (B30).** Liên kết tài khoản Project Sekai server **EN** hoặc **JP** qua xác minh Bio trong game (`/pjsk link`), đồng bộ dữ liệu FC/AP qua Transfer ID trong DM và nhận lại ngay **Transfer ID + mật khẩu mới** (`/pjsk sync`, kèm cơ chế khôi phục `/pjsk recover` và nhập thủ công file `suite.json` qua `/pjsk import`), sau đó render ảnh **Best 30** (`/b30` / `/pjsk b30`) theo bảng hằng số của `pjskb30`.
- **Tiện ích khác.** Tra cứu sản phẩm Mercari Nhật theo link hoặc ID kèm ước tính giá VND, và xem giá xăng dầu PVOIL hôm nay tại Việt Nam.

## Danh sách lệnh

Lệnh Slash (`/`) là cách dùng chính; nhiều lệnh cũng hỗ trợ dạng Prefix (`!` hoặc `-`). Minigame đoán nhạc và các lệnh cài đặt server chỉ dùng được trong server. Gõ `/help` để xem tổng quan và `/help <danh mục>` để xem chi tiết từng nhóm.

| Lệnh Slash | Prefix | Chức năng |
|---|---|---|
| `/card <name>` | | Tra cứu thẻ theo tên hoặc ID |
| `/gacha pull [amount]` | | Quay gacha 1 hoặc 10 thẻ |
| `/gacha pity` | | Kiểm tra số pity hiện tại |
| `/song search <query>` | `!song <query>` | Tìm kiếm bài hát |
| `/song info <name>` | | Xem chi tiết một bài hát |
| `/song random` | `!songr` | Chọn ngẫu nhiên một bài hát |
| `/profile info <name>` | `!profile <name>` | Xem hồ sơ chi tiết nhân vật |
| `/event current` | `!event` | Xem sự kiện đang diễn ra hoặc sắp tới |
| `/event history` | `!events` | Xem lịch sử các sự kiện |
| `/event search <name>` | `!eventsearch <name>` | Tìm kiếm sự kiện |
| `/birthday check` | `!bday` | Xem sinh nhật hôm nay và sắp tới |
| `/birthday countdown [name]` | `!bdayu [name]` | Đếm ngược ngày sinh nhật kèm ảnh thẻ |
| `/guess [mode]` | | Bắt đầu trò chơi đoán nhân vật (easy / normal / hard) |
| `/guessmode [mode]` | | Đặt hoặc xem độ khó mặc định cho `/guess` |
| `/songguess [mode] [pool]` | `!sg`, `!sgv`, `!sga`, `!sgav` | Chơi đoán nhạc trong voice (`v`: có hiệu ứng, `a`: toàn bộ bài hát) |
| `/mercari <link hoặc ID>` | `!mercari`, `!mer` | Tra cứu sản phẩm trên Mercari Nhật |
| `/pjsk link [region]` | | Liên kết tài khoản PJSK (EN/JP) qua Bio |
| `/pjsk unlink [region]` | | Hủy liên kết và xóa dữ liệu đã lưu |
| `/pjsk profile [region] [user]` | | Xem hồ sơ PJSK đã liên kết |
| `/pjsk sync [region]` | | Đồng bộ FC/AP qua Transfer ID (trong DM) và nhận lại Transfer ID mới |
| `/pjsk recover [region]` | | Cấp lại Transfer ID mới nếu quá trình sync bị gián đoạn |
| `/pjsk import [region] <file>` | | Nhập dữ liệu FC/AP từ file `suite.json` |
| `/b30 [region] [user]` | | Render ảnh bảng xếp hạng Best 30 (B30) |
| `/gasprice` | `!gasprice` | Xem giá xăng dầu PVOIL hôm nay |

Trong cả 2 minigame (`/guess` và `/songguess`), trả lời bằng `-g <đáp án>` tại kênh đang diễn ra ván chơi.

Các lệnh cài đặt server yêu cầu quyền **Quản lý máy chủ (Manage Server)**: `/birthday channel`, `/birthday disable`, `/cotd channel`, `/cotd interval`, `/cotd now` và `/cotd disable` (riêng `/cotd status` ai cũng xem được). Lệnh `/update_data` để kiểm tra cập nhật dữ liệu ngay lập tức yêu cầu quyền **Quản trị viên (Administrator)**.

## Quyền bot cần thiết

Link mời bot yêu cầu các quyền: *Send Messages*, *Embed Links*, *Attach Files*, *Add Reactions*, *Read Message History*; *Connect* và *Speak* cho trò chơi đoán nhạc; cùng *Use Application Commands* cho lệnh Slash.

## Tự host bot

### Yêu cầu môi trường

- Python **3.11** trở lên.
- **FFmpeg** có sẵn trong `PATH` (cho trò chơi đoán nhạc). Trên Linux cần cài thêm `libopus`.
- Một ứng dụng Discord đã tạo Bot Token. Trong Discord Developer Portal, nhớ bật **Message Content Intent** (cần thiết cho lệnh prefix và câu trả lời `-g`).

### Cài đặt và khởi chạy

```bash
git clone https://github.com/kei-kochiya/IchikaBot.git
cd IchikaBot
pip install -r requirements.txt
cp .env.example .env
```

Điền token của bot vào file `.env`, sau đó chạy:

```bash
python bot.py
```

Lệnh Slash được đồng bộ tự động mỗi khi bot khởi động. Chủ bot cũng có thể ép đồng bộ lại bất cứ lúc nào bằng `!sync`.

### Biến môi trường (`.env`)

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `DISCORD_TOKEN` | Có | Token của Discord bot |
| `LOG_LEVEL` | Không | `DEBUG`, `INFO` (mặc định), `WARNING` hoặc `ERROR` |
| `PJSK_EN_INHERIT_TOKEN` | Không | Secret JWT để ký header `x-inherit-id-verify-token` cho `/pjsk sync` server **EN** |
| `PJSK_JP_INHERIT_TOKEN` | Không | Secret JWT để ký header `x-inherit-id-verify-token` cho `/pjsk sync` server **JP** |

> [!IMPORTANT]
> **Lưu ý về JWT Token (`PJSK_EN_INHERIT_TOKEN` / `PJSK_JP_INHERIT_TOKEN`):**
> Hai secret JWT dùng để xác thực Transfer ID **không được cung cấp sẵn** trong repository này — nếu muốn bật tính năng `/pjsk sync` khi tự host, **bạn phải tự tìm / tự xin quyền sử dụng các JWT secret này** rồi điền vào file `.env` (tuyệt đối không commit `.env` lên git).
>
> Nếu chưa có JWT secret, bot vẫn hoạt động bình thường với đầy đủ các tính năng khác, và người dùng vẫn có thể tạo bảng `/b30` bằng cách tải lên file `suite.json` thông qua lệnh `/pjsk import`.

### Dữ liệu và thư mục cục bộ

| Đường dẫn | Nội dung | Nguồn |
|---|---|---|
| `gameData/static/` | Dữ liệu nhân vật, biệt danh và danh sách nhạc đoán bài (`song.xlsx`) | Có sẵn trong repo; cập nhật bằng `git pull` |
| `gameData/JP_data/`, `gameData/EN_data/` | Dữ liệu thẻ, bài hát và sự kiện | Tự tải ở lần chạy đầu (~70 MB), sau đó tự kiểm tra mỗi 6 giờ |
| `music/` | File âm thanh cho minigame đoán nhạc, đặt tên theo ID bài hát (`54.mp3`) | Không có trong repo — bạn cần tự bổ sung |
| `ichika.db` | SQLite lưu pity gacha, cài đặt server và dữ liệu PJSK/B30 | Tự tạo ở lần chạy đầu |
| `.gachacache/` | Cache ảnh thẻ, jacket bài hát và hằng số B30 | Tự tạo lại khi cần; có thể xóa an toàn |

Ở lần khởi chạy đầu tiên, các lệnh tra cứu thẻ/nhạc/sự kiện sẽ chưa có dữ liệu cho tới khi tải xong `JP_data` và `EN_data` (thường mất khoảng 1 phút).

### Di chuyển bot sang máy chủ khác

Tắt bot trước, sau đó sao chép `.env`, `music/` và `ichika.db` sang máy mới. Nếu sao chép thêm `gameData/JP_data`, `gameData/EN_data` và `gameData/updaterState.json`, bot sẽ bỏ qua bước tải dữ liệu lần đầu.

## Phát triển & Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
ruff format --check .
```

Bộ test mặc định chạy hoàn toàn offline. Các bài test kiểm tra hợp đồng với API thật bên ngoài được đánh dấu `@pytest.mark.live` và có thể chạy riêng bằng `pytest -m live`. GitHub Actions CI tự động chạy test trên Python 3.11 – 3.13, kiểm tra lint/format bằng `ruff` và kiểm tra lỗ hổng thư viện bằng `pip-audit`.

## Tài liệu

- **Tiếng Việt:** [Kiến trúc & Hướng dẫn đóng góp (`docs/vi/ARCHITECT.md`)](docs/vi/ARCHITECT.md)
- **English:** [English README (`docs/en/README.md`)](docs/en/README.md) · [Architecture & Contribution Guide (`docs/en/ARCHITECT.md`)](docs/en/ARCHITECT.md)

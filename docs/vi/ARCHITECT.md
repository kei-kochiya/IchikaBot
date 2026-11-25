# Kiến trúc IchikaBot & Hướng dẫn đóng góp

[![English](https://img.shields.io/badge/Docs-English-blue)](../en/ARCHITECT.md) [![README (VI)](https://img.shields.io/badge/README-Tiếng_Việt-green)](../../README.md)

Chào mừng bạn đến với mã nguồn **IchikaBot**! Tài liệu này trình bày tổng quan về kiến trúc nội bộ, cấu trúc thư mục và mối quan hệ phụ thuộc giữa các module — dành cho lập trình viên muốn tìm hiểu hoặc đóng góp vào dự án.

## Tổng quan kiến trúc

IchikaBot được xây dựng bằng `discord.py` theo **kiến trúc module hóa dạng Cog (Cog-based architecture)**. Mỗi nhóm tính năng chính được đóng gói thành một lớp Cog độc lập trong các thư mục con dưới `cogs/`.

Để đảm bảo tốc độ phản hồi cao nhưng vẫn giữ mức tiêu thụ **RAM khi nhàn rỗi (idle RAM) ở mức thấp (~74 MB)**, bot áp dụng mô hình **Singleton** cho các bộ nạp dữ liệu game lớn, kết hợp streaming JSON và lazy import cho các thư viện nặng. Dữ liệu bền vững được lưu qua SQLite bất đồng bộ (`aiosqlite`). Logic được tách rõ giữa lớp giao tiếp lệnh Discord (`cogs/`) và lớp nghiệp vụ/dữ liệu/UI (`utils/`).

---

## Lớp tiện ích & Logic cốt lõi (`utils/`)

Thư mục `utils/` là xương sống của bot. Các Cog nên gọi lại các tiện ích ở đây thay vì tự xử lý logic phức tạp hay tự đọc file JSON thô.

### `utils/data/` (Quản lý dữ liệu game)
- **`game_data.py`**: Singleton (`game_data`) quản lý thông tin nhân vật, nhóm (unit), mã màu, hồ sơ (`characterProfiles.json`) và biệt danh (`nicknames.json`).
- **`card_data.py`**: Singleton (`card_data`) đọc và lưu cache toàn bộ dữ liệu thẻ (`cards.json`) trong bộ nhớ với bảng tra cứu `O(1)` và tiêu đề EN/JP.
- **`event_data.py`**: Singleton (`event_data`) quản lý dữ liệu sự kiện JP/EN (`events.json`), sự kiện đang diễn ra/đã qua và lịch banner.
- **`song_data.py`**: Singleton (`song_data`) quản lý danh sách bài hát (`musics.json`) và độ khó chart (`musicDifficulties.json`).
- **`music_quiz_db.py`**: Lớp cơ sở dữ liệu (`MusicQuizDB`) cho file `song.xlsx` dùng trong minigame đoán nhạc, kèm hàm chuẩn hóa câu trả lời `normalize()` dùng chung cho cả 2 trò chơi `-g`. Kết quả đọc Excel được cache sang JSON (`.gachacache/song_db_cache.json`, theo kích thước và `mtime` của file), nhờ vậy thư viện `openpyxl` (~16 MB RAM) chỉ được import khi `song.xlsx` thực sự thay đổi.
- **Được sử dụng bởi**: Hầu hết các cog game và tra cứu (`birthday.py`, `guess.py`, `profile.py`, `card.py`, `events.py`, `songs.py`, `pjsk.py`).

### `utils/core/` (Hệ thống cốt lõi)
- **`database.py`**: Xử lý toàn bộ thao tác bất đồng bộ với `ichika.db` (pity gacha, cài đặt server, liên kết & lịch sử clear PJSK) trên một kết nối SQLite dùng chung sống lâu dài (chế độ WAL). Toàn bộ thao tác ghi đi qua `_write_tx()` có khóa tuần tự và rollback an toàn khi gặp lỗi/hủy task. Đóng sạch bằng `close_db()` khi tắt bot.
- **`autoupdater.py`**: Kiểm tra, tải và đồng bộ dữ liệu mới từ kho Sekai-World. Sử dụng request có điều kiện (ETag lưu ở `gameData/updaterState.json`) để file không đổi chỉ tốn phản hồi 304 cực nhẹ, stream tải thẳng ra ổ đĩa, kiểm tra hợp lệ mà không dựng cây JSON trong RAM và ghi đè file nguyên tử (`os.replace`). Chỉ cho phép 1 tiến trình cập nhật chạy tại một thời điểm.
- **`jsonstream.py`**: `iter_json_array()` trả về từng phần tử của các mảng JSON rất lớn theo kiểu stream (hỗ trợ mọi kiểu định dạng). Luôn dùng hàm này thay cho `json.load` với các file dữ liệu game dung lượng lớn.
- **`tasks.py`**: `spawn()` / `react_in_background()` giúp chạy các tác vụ nền an toàn mà không bị garbage collector thu hồi sớm hay để lọt cảnh báo `"Task exception was never retrieved"`.
- **`romaji.py`**: Chuẩn hóa chuỗi và chuyển đổi Romaji phục vụ tìm kiếm đa ngôn ngữ (JP/EN/Romaji).

### `utils/media/` (Xử lý hình ảnh & âm thanh)
- **`image_helper.py`**: Tải và cache ảnh bất đồng bộ. Ảnh thẻ được lưu dạng WebP (nhỏ hơn PNG gốc từ CDN khoảng 20 lần: tiết kiệm băng thông tải, ổ đĩa và thời gian gửi lên Discord); gửi đi dưới tên `card.webp`. Ghi file nguyên tử, gộp nhiều yêu cầu trùng nhau cho cùng một ảnh thành 1 lượt tải duy nhất (`_inflight`), nhớ lỗi 404 từ CDN trong 1 giờ, và lỗi mạng không kích hoạt tải fallback tràn lan. Đồng thời hỗ trợ cache jacket bài hát cho B30.
- **`card_focus.py`**: Tự động định vị nhân vật trên ảnh thẻ cho chế độ Dễ của `/guess`, dựa vào phân bố màu từ ảnh `member_cutout` kết hợp độ sắc nét (vì ảnh cutout là bố cục vẽ lại nên không thể khớp pixel trực tiếp). Chỉ dùng Pillow, xử lý trong ~0.1 giây.
- **`gacha_render.py`**: Vẽ ảnh kết quả quay gacha theo phong cách màn hình kết quả trong game (nền, ảnh thẻ, sao hiếm và biểu tượng thuộc tính). Tài nguyên UI tải 1 lần vào `.gachacache/ui`; thumbnail thẻ cache ở `.gachacache/tiles`. Mọi tài nguyên đều có phương án vẽ dự phòng nếu thiếu.
- **`audio_fx.py`**: Xử lý cắt nhạc và hiệu ứng âm thanh (FFmpeg/Pydub). Đoạn nhạc được cắt trực tiếp bằng `ffmpeg` seek nên không bao giờ phải giải mã cả bài hát vào RAM.

### Các nhóm tiện ích theo tính năng
- **`utils/game/`**: Lọc thẻ, chọn ngẫu nhiên, kiểm tra ảnh thường/sau nâng cấp (`cards.py`) và bộ lọc/chọn bài hát + chuẩn hóa đáp án cho minigame đoán nhạc (`music_helpers.py`).
- **`utils/social/`**: Tính toán ngày theo múi giờ JST và dựng Embed/View cho tính năng sinh nhật (`birthday_helpers.py`, `birthday_ui.py`).
- **`utils/info/`**: Dựng Embed và giao diện phân trang dùng chung (`songs_ui.py`, `events_ui.py`).
- **`utils/mercari_scraper/`**: Tra cứu sản phẩm Mercari Nhật hỗ trợ cả tin đăng cá nhân C2C (`c2c_client.py`) và Mercari Shops (`shops_client.py` dùng chung `aiohttp`). `AsyncC2CClient` (cùng `mercapi`/`httpx`, ~12 MB) chỉ được lazy import ở lần tra cứu C2C đầu tiên; phần phân tích URL nhẹ nằm riêng trong `urls.py`.
- **`utils/pjsk/`**: Bộ client & engine tính B30 cho Project Sekai (EN & JP), được lazy-load hoàn toàn: mã hóa AES-128-CBC + MessagePack (`crypto.py`), client bất đồng bộ hỗ trợ tra cứu hồ sơ công khai và đồng bộ Transfer ID có cơ chế crash-recovery (`client.py`), giao diện Modal/View & gửi DM (`ui.py`), bộ tải & tính hằng số chart từ Google Sheets `pjskb30` (`constants.py`), và bộ render ảnh thẻ B30 kích thước 1000×1500 bằng Pillow (`b30_render.py`). Hai thư viện `cryptography` và `msgpack` không bao giờ bị import lúc khởi động bot.

---

## Các nhóm tính năng (`cogs/`)

Các Cog được phân loại vào từng thư mục con theo chức năng. Bot tự động quét và nạp đệ quy toàn bộ file `.py` trong cây thư mục này.

| Thư mục | Chức năng chính | Phụ thuộc tiêu biểu |
|:---|:---|:---|
| **`cogs/voice/`** | Minigame đoán nhạc trong kênh voice (`music_guess.py`). | `utils.media.audio_fx`, `utils.data.music_quiz_db`, `utils.game.music_helpers` |
| **`cogs/game/`** | Đoán nhân vật qua ảnh thẻ (`guess.py`) & Giả lập quay gacha (`gacha.py`). | `utils.data.*`, `utils.game.*`, `utils.core.database` |
| **`cogs/info/`** | Tra cứu Thẻ, Hồ sơ, Bài hát, Sự kiện & Liên kết tài khoản / đồng bộ / B30 PJSK (`pjsk.py`). | `utils.info.*`, `utils.data.*`, `utils.pjsk.*`, `utils.core.romaji` |
| **`cogs/social/`** | Tương tác cộng đồng: Sinh nhật nhân vật (`birthday.py`), Card of the Day (`card_of_day.py`). | `utils.social.*`, `utils.data.*`, `utils.core.database` |
| **`cogs/system/`** | Quản trị bot: Tự động cập nhật dữ liệu (`data_updater.py`), Trợ giúp tương tác (`help.py`). | `utils.core.autoupdater` |
| **`cogs/misc/`** | Tiện ích: Tra cứu Mercari Nhật (`mercari.py`) & Giá xăng dầu Việt Nam (`gas_price.py`). | `utils.mercari_scraper.*`, `aiohttp` |

---

## Ví dụ luồng dữ liệu: Cập nhật dữ liệu game tự động

1. `cogs/system/data_updater.py` chạy tác vụ nền theo chu kỳ (mỗi 6 giờ).
2. Gọi `utils/core/autoupdater.py` để kiểm tra ETag và tải các file mới từ kho Sekai-World.
3. Khi có dữ liệu mới, hệ thống gọi reload các singleton tương ứng (`card_data`, `event_data`, `song_data`).
4. Các Cog có phương thức `load_data()` được thông báo để làm mới bộ đệm trong bộ nhớ mà không cần khởi động lại bot.

---

## Nguyên tắc đóng góp

1. **Tối ưu RAM**: Luôn dùng các singleton từ `utils.data` thay vì tự mở và parse lại JSON. Khi cần đọc file dữ liệu lớn, hãy stream bằng `utils.core.jsonstream.iter_json_array` và chỉ giữ lại các trường thực sự dùng tới. Lazy import các thư viện nặng chỉ phục vụ một lệnh riêng lẻ (tham khảo `utils/mercari_scraper/__init__.py` và `utils/pjsk/`): Python không giải phóng module sau khi import, nên eager import sẽ chiếm RAM suốt vòng đời tiến trình.
2. **Tách biệt trách nhiệm**: Giữ các file Cog gọn gàng. Đưa phần dựng Embed, Pagination UI và xử lý tính toán phức tạp vào thư mục `utils/` tương ứng.
3. **Lưu trữ bền vững**: Thêm bảng và hàm thao tác vào `utils/core/database.py` (dùng `_write_tx()` cho mọi thao tác ghi).
4. **Không chặn Event Loop**: Các tác vụ CPU/I/O nặng (Pillow, Pydub, đọc file lớn) bắt buộc phải chạy qua `asyncio.to_thread()` hoặc `loop.run_in_executor()`.
5. **Đường dẫn nhất quán**: Luôn dùng `BASE_DIR` và các hằng số đường dẫn từ `config.py` để đảm bảo tương thích trên cả Windows, Linux và Docker.

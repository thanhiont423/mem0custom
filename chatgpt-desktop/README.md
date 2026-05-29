# ChatGPT Desktop — Chat History Export

[🇻🇳 Tiếng Việt](#tiếng-việt) | [🇬🇧 English](#english)

---

## Tiếng Việt

### Giới thiệu

**ChatGPT Desktop** là ứng dụng desktop wrapper cho [chatgpt.com](https://chatgpt.com), bổ sung tính năng **xuất chat history tự động dưới dạng JSON** để tích hợp với hệ thống mem0 (long-term memory). Dựa trên dự án mã nguồn mở [lencx/ChatGPT](https://github.com/lencx/ChatGPT) (Tauri 2.0).

### Tính năng chính

- 🔄 **Tự động ghi log mọi tin nhắn** user gõ và assistant trả lời, song song với chat bình thường
- 💾 **Xuất từng phiên ra file JSON riêng** khi user gõ keyword `compact` hoặc `lưu`
- 🛡️ **Chống mất data khi crash** — dùng Write-Ahead Log (WAL), tự phục hồi khi mở lại app
- 📦 **Tự động flush khi đóng app** — không cần nhớ gõ keyword trước khi tắt
- 🆔 **Tên file rõ ràng**: `session_{id}_{YYYYMMDD-HHMMSS}.json`

### Cài đặt

#### Cách 1 — Tải installer (Windows, recommended)

1. Vào [Releases](https://github.com/thanhiont423/mem0custom/releases/latest)
2. Tải 1 trong 3 file:
   - `ChatGPT_2.0.0_x64-setup.exe` — NSIS installer (3 MB, nhỏ gọn)
   - `ChatGPT_2.0.0_x64_en-US.msi` — MSI installer (15 MB, chuẩn enterprise)
   - `chatgpt.exe` — Portable, không cần cài
3. Double-click để cài
4. Yêu cầu: Windows 10+, Microsoft Edge WebView2 Runtime (thường có sẵn)

#### Cách 2 — Build từ source

```powershell
git clone https://github.com/thanhiont423/mem0custom.git
cd mem0custom/chatgpt-desktop
.\build-windows.ps1
```

Script tự cài Rust + WebView2 + chạy test + build. Mất ~15-20 phút lần đầu.

### Cách sử dụng

1. Mở app → màn hình ChatGPT.com hiện ra → đăng nhập như bình thường
2. Chat thoải mái — mọi message đều được ghi log ngầm
3. Khi muốn xuất phiên hiện tại, gõ một trong các keyword sau ở **ô input "Ask"** (dưới cùng):
   - `compact`
   - `/compact`
   - `lưu`
   - `/lưu`
   - `luu` (fallback không dấu)
4. App tự sinh file JSON tại `%APPDATA%\com.nofwl.chatgpt\sessions\`
5. Ô input tự clear, phiên mới bắt đầu (session_id khác)

### Cấu trúc file JSON

```json
{
  "session_id": "s7a3f2b9",
  "started_at": 1748430000,
  "started_at_iso": "2026-05-28T13:00:00+07:00",
  "exported_at": 1748441422,
  "exported_at_iso": "2026-05-28T14:30:22+07:00",
  "exported_via": "compact",
  "message_count": 12,
  "messages": [
    {
      "id": "msg-abc",
      "conversation_id": "67abc...",
      "role": "user",
      "content": "Xin chào",
      "captured_at": 1748441100
    },
    {
      "id": "msg-def",
      "conversation_id": "67abc...",
      "role": "assistant",
      "content": "Chào bạn, có thể giúp gì?",
      "captured_at": 1748441120
    }
  ]
}
```

### Vị trí file

| OS | Đường dẫn |
|----|-----------|
| Windows | `%APPDATA%\com.nofwl.chatgpt\sessions\` |
| macOS | `~/Library/Application Support/com.nofwl.chatgpt/sessions/` |
| Linux | `~/.config/com.nofwl.chatgpt/sessions/` |

### Crash recovery

Khi app bị crash hoặc tắt đột ngột (mất điện, force kill):
1. Mở lại app
2. App phát hiện WAL còn data từ phiên cũ
3. Tự động chuyển thành file `sessions/recovered/session_recovered_*.json`
4. Xoá WAL cũ, tạo phiên mới sạch

File recovery có flag `"exported_via": "crash_recovery"` để process bên ngoài biết.

### Tích hợp mem0custom server

Pattern khuyến nghị: tiến trình Python/Node watch folder `sessions/`, đọc file mới → POST lên `archive-api`:

```python
import json, time, shutil
from pathlib import Path

SESSIONS = Path.home() / "AppData/Roaming/com.nofwl.chatgpt/sessions"
PROCESSED = SESSIONS / "processed"
PROCESSED.mkdir(exist_ok=True)

while True:
    for f in sorted(SESSIONS.glob("session_*.json")):
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
            # TODO: POST data lên mem0custom server
            shutil.move(f, PROCESSED / f.name)
    time.sleep(10)
```

### Acceptance test

Sau khi cài, chạy:

```powershell
python acceptance_test.py
```

Test 10 yêu cầu: app data structure, session_id format, file naming, JSON schema, message schema, separate files per session, recovery, NDJSON WAL, no SQLite.

### ☕ Buy Me a Coffee

Nếu bạn thấy hữu ích, ủng hộ tác giả qua chuyển khoản ngân hàng Việt Nam:

- **Số tài khoản:** `0869649888`
- **Hỗ trợ:** Tất cả ngân hàng VN (Vietcombank, Techcombank, MB, BIDV, ACB, VPBank, TPBank, MoMo, ZaloPay...)
- **Tên người nhận:** Liên hệ trước khi chuyển

Cảm ơn bạn rất nhiều! 🙏

### ⚠️ Tuyên bố miễn trừ trách nhiệm

**Phần mềm này chỉ được phép sử dụng cho mục đích cá nhân (personal use).**

❌ **NGHIÊM CẤM:**
- Sử dụng cho mục đích thương mại (bán, cho thuê, SaaS)
- Tái phân phối có thu phí
- Sử dụng tại tổ chức/công ty mà không có thỏa thuận riêng

✅ **CHO PHÉP:**
- Tải về và dùng cá nhân
- Sửa đổi cho mục đích học tập
- Đóng góp pull request về upstream

**Tác giả không chịu trách nhiệm về:**
- Mất mát dữ liệu (kể cả file chat history)
- Việc account ChatGPT bị suspend (do OpenAI có thể coi đây là automation)
- Bất kỳ thiệt hại nào phát sinh từ việc sử dụng

App scrape DOM `chatgpt.com` — nếu OpenAI thay đổi giao diện, tính năng có thể ngừng hoạt động đến khi update.

---

## English

### Overview

**ChatGPT Desktop** is a desktop wrapper for [chatgpt.com](https://chatgpt.com) with **automatic chat history export to JSON** for integration with mem0 (long-term memory) systems. Based on the open-source [lencx/ChatGPT](https://github.com/lencx/ChatGPT) project (Tauri 2.0).

### Features

- 🔄 **Auto-log every message** (user prompts + assistant responses) silently
- 💾 **Export per-session JSON files** when user types `compact` keyword
- 🛡️ **Crash-safe via Write-Ahead Log (WAL)** — auto-recovers on next app start
- 📦 **Auto-flush on app exit** — no need to remember triggering export
- 🆔 **Clear filenames**: `session_{id}_{YYYYMMDD-HHMMSS}.json`

### Installation

#### Option 1 — Download installer (Windows, recommended)

1. Go to [Releases](https://github.com/thanhiont423/mem0custom/releases/latest)
2. Download one of:
   - `ChatGPT_2.0.0_x64-setup.exe` — NSIS installer (3 MB)
   - `ChatGPT_2.0.0_x64_en-US.msi` — MSI installer (15 MB, enterprise-friendly)
   - `chatgpt.exe` — Portable, no install needed
3. Double-click to install
4. Requires: Windows 10+, Microsoft Edge WebView2 Runtime (usually pre-installed)

#### Option 2 — Build from source

```powershell
git clone https://github.com/thanhiont423/mem0custom.git
cd mem0custom/chatgpt-desktop
.\build-windows.ps1
```

Auto-installs Rust + WebView2, runs tests, builds. Takes ~15-20 min on first run.

### Usage

1. Launch app → ChatGPT.com loads → sign in normally
2. Chat freely — every message is silently logged
3. To export the current session, type one of these in the **"Ask" input** (bottom of app):
   - `compact`
   - `/compact`
   - `lưu` (Vietnamese: "save")
   - `/lưu`
   - `luu` (no diacritics)
4. App writes JSON to `%APPDATA%\com.nofwl.chatgpt\sessions\`
5. Input clears, new session starts (different session_id)

### JSON File Structure

```json
{
  "session_id": "s7a3f2b9",
  "started_at": 1748430000,
  "started_at_iso": "2026-05-28T13:00:00+07:00",
  "exported_at": 1748441422,
  "exported_at_iso": "2026-05-28T14:30:22+07:00",
  "exported_via": "compact",
  "message_count": 12,
  "messages": [
    {
      "id": "msg-abc",
      "conversation_id": "67abc...",
      "role": "user",
      "content": "Hello",
      "captured_at": 1748441100
    }
  ]
}
```

### File Locations

| OS | Path |
|----|------|
| Windows | `%APPDATA%\com.nofwl.chatgpt\sessions\` |
| macOS | `~/Library/Application Support/com.nofwl.chatgpt/sessions/` |
| Linux | `~/.config/com.nofwl.chatgpt/sessions/` |

### Crash Recovery

If app crashes or is killed:
1. Reopen app
2. App detects orphan WAL from previous session
3. Auto-converts to `sessions/recovered/session_recovered_*.json`
4. Removes old WAL, creates fresh session

Recovered files have `"exported_via": "crash_recovery"` flag.

### Integration with mem0custom Server

Recommended pattern — watch the `sessions/` folder from an external process:

```python
import json, time, shutil
from pathlib import Path

SESSIONS = Path.home() / "AppData/Roaming/com.nofwl.chatgpt/sessions"
PROCESSED = SESSIONS / "processed"
PROCESSED.mkdir(exist_ok=True)

while True:
    for f in sorted(SESSIONS.glob("session_*.json")):
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
            # TODO: POST to mem0custom archive-api
            shutil.move(f, PROCESSED / f.name)
    time.sleep(10)
```

### Acceptance Tests

After install, verify with:

```powershell
python acceptance_test.py
```

Tests 10 requirements: app data structure, session_id format, file naming, JSON schema, message schema, separate files per session, recovery, NDJSON WAL, no SQLite.

### ☕ Buy Me a Coffee

If you find this useful, support the author via Vietnamese bank transfer:

- **Account number:** `0869649888`
- **Banks supported:** All Vietnamese banks (Vietcombank, Techcombank, MB, BIDV, ACB, VPBank, TPBank, MoMo, ZaloPay, etc.)
- **Account holder name:** Contact before transferring

Thank you very much! 🙏

### ⚠️ Disclaimer

**This software is permitted for PERSONAL USE ONLY.**

❌ **PROHIBITED:**
- Commercial use (selling, renting, SaaS)
- Paid redistribution
- Use at organizations/companies without separate agreement

✅ **PERMITTED:**
- Personal download and use
- Modification for educational purposes
- Pull request contributions to upstream

**The author is NOT liable for:**
- Data loss (including chat history files)
- ChatGPT account suspension (OpenAI may flag this as automation)
- Any damages arising from use

The app scrapes the `chatgpt.com` DOM — if OpenAI changes their UI, features may break until updated.

---

## License & Credits

- Base project: [lencx/ChatGPT](https://github.com/lencx/ChatGPT) — AGPL-3.0
- Chat history feature: Add-on, personal-use only (see disclaimer above)
- Built with: Tauri 2.0, Rust, React, TypeScript

## Links

- 🐙 Source: https://github.com/thanhiont423/mem0custom
- 📦 Releases: https://github.com/thanhiont423/mem0custom/releases
- 🐛 Issues: https://github.com/thanhiont423/mem0custom/issues
- 💬 mem0 server: https://github.com/thanhiont423/mem0custom (same repo, `main` branch)

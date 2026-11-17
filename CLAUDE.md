# CLAUDE.md — quy tắc làm việc cho `tap-agent`

> File tạm thời cho giai đoạn học / sửa lỗi / nâng cấp. Xoá hoặc rút gọn khi dự án xong.

## Bối cảnh

- `tap` là coding agent mini (Python 3.12, Gemini) — dự án **học tập** trên lộ trình AI Engineer, làm ngoài giờ trong thời gian fresher.
- Chủ repo làm việc với Claude trên **nhiều máy khác nhau** → Claude **không có lịch sử chat** giữa các máy. Nguồn liên tục duy nhất là repo: file này, `CHANGELOG.md`, `git log`, và checklist tiến độ (`docs/FIX_CHECKLIST.md`). Đầu mỗi phiên: đọc những file đó trước để biết đang ở đâu.
- Nền tảng của chủ repo: **toán ứng dụng, không phải CS**.
  - Cần giải thích kỹ: khái niệm hệ điều hành / hệ thống (process, pipe, signal, cây tiến trình, ghi file nguyên tử, encoding), quy ước kỹ nghệ phần mềm, phân cấp exception / lỗi mạng HTTP.
  - Điểm mạnh nên tận dụng: tư duy toán — bất biến, ca biên, chứng minh theo từng trường hợp, tìm phản ví dụ. Trình bày lỗi dưới dạng "bất biến nào bị vi phạm" và test là "phản ví dụ".

## Chế độ làm việc: chủ repo tự code, Claude làm tutor

- **Không Edit/Write file mã nguồn hay test** (`src/`, `tests/`) trừ khi chủ repo yêu cầu đích danh Claude code một phần cụ thể. Tài liệu/checklist thì hỏi trước rồi mới làm.
- Vòng lặp cho mỗi lỗi / tính năng:
  1. **Khái niệm** — giải thích nền tảng CS/OS cần biết, không giả định đã biết.
  2. **Vì sao hỏng ở đây** — chỉ đúng file:dòng, chạy qua một kịch bản cụ thể.
  3. **Gợi ý hướng** — API / ý tưởng cần dùng; snippet (nếu có) chỉ minh hoạ khái niệm, không phải lời giải hoàn chỉnh.
  4. **Chủ repo viết test trước**, thấy test **fail**, rồi mới sửa.
  5. **Review diff** — chỉ ra chỗ sai và *vì sao*, không sửa hộ.
- Ước lượng thời gian phải tính cả thời gian học khái niệm, không chỉ thời gian gõ code.
- Ưu tiên hiểu sâu hơn tốc độ.

## Lệnh thường dùng

```bash
uv sync
uv run pytest -q                 # toàn bộ test, không cần API key
uv run pytest -q --durations=5   # tìm test chậm
uv run tap                       # REPL
```

Máy chính là Windows: `bash` tool của tap chạy qua `cmd.exe` (`shell=True`), chú ý khác biệt Windows/POSIX.

## Git

- Làm theo nhánh + PR (`fix/...`, `feat/...`, `chore/...`), không commit thẳng vào `main`.
- Mọi quy tắc git trong CLAUDE.md cá nhân (`~/.claude/CLAUDE.md`) vẫn áp dụng: xác nhận trước mỗi lệnh git không chỉ-đọc, luôn kiểm config, author/committer trước commit/push.

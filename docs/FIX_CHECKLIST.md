# Kế hoạch sửa lỗi trước khi nâng cấp `tap`

> Lập ngày 2026-11-17, trên `main` @ `a3afd2f` cộng với các thay đổi chưa commit ở `cli.py` và `.env.example`.
> Số dòng ghi trong file này đúng tại thời điểm lập; khi bạn bắt đầu sửa, số dòng sẽ lệch, nên **tìm theo tên hàm**.
> Cách làm việc (bạn tự code, Claude làm tutor) xem ở [`CLAUDE.md`](../CLAUDE.md).

## Bảng tiến độ

| PR | Nhánh | Nội dung | Ước lượng (gồm thời gian học) | Trạng thái |
|---|---|---|---|---|
| 0 | `chore/add-claude-md` | Chuẩn bị | 0.5h | ◐ |
| 1 | `fix/transcript-integrity` | #1, #1b, #7 | 4–6h | ☐ |
| 2 | `fix/bash-process-tree` | #2 | 6–10h | ☐ |
| 3 | `fix/bash-blocklist` | #4 | 2–3h | ☐ |
| 4 | `fix/read-edit-edges` | #3, #5, E, F | 4–6h | ☐ |
| 5 | `fix/provider-robustness` | #9, #10, #11 | 6–8h | ☐ |
| 6 | `fix/session-cli` | #6, #8 | 3–4h | ☐ |
| 7 | `chore/prompt-env-and-cleanup` | D, H | 2–3h | ☐ |
| | | **Cộng** | **khoảng 28–40h**, cộng review thành **khoảng 35–50h** | |

Ký hiệu trạng thái: ☐ chưa làm · ◐ đang làm · ☑ đã merge

**Thứ tự:** hiện xếp theo **mức nghiêm trọng**. Có một phương án khác là xếp theo **độ khó tăng dần**: 0 → 1 → 4 → 6 → 5 → 2 → 3 → 7. Phương án này giúp có đà ngay từ đầu; đổi lại, lỗi treo của `bash` sẽ được sửa muộn hơn. Bạn chưa chọn thì giữ thứ tự hiện tại.

**Mức độ chắc chắn:** mọi lỗi dưới đây đều **đã chạy thử để xác nhận**, chỉ trừ F (ghi file không nguyên tử), D và H. Ba mục này là nhận định rút ra từ việc đọc code.

---

## Quyết định đang chờ

| # | Câu hỏi | Mặc định nếu chưa quyết | Cần chốt trước |
|---|---|---|---|
| Q1 | Lớp xin phép người dùng (human-in-the-loop) làm ngay đợt này, hay để sang giai đoạn nâng cấp? | Để sang nâng cấp; đợt này chỉ sửa README cho đúng | PR 3 |
| Q2 | Throttle mặc định: giữ 10 RPM (an toàn với gói free) hay 0 (nhanh, dựa vào retry khi gặp 429)? | Giữ 10 và cho phép cấu hình | PR 5 |
| Q3 | `/clear` sẽ tạo session mới như `/new`, hay chỉ ghi một dấu mốc vào file cũ? | Tạo session mới | PR 6 |
| Q4 | `.tap-sessions` giữ trong repo hay chuyển ra `~/.tap/sessions/`? | Giữ nguyên, xem lại khi nâng cấp | sau đợt này |

---

## PR 0 — Chuẩn bị

- [ ] Commit các thay đổi đang dở ở `src/tap/cli.py` (dọn import, đổi `str(value)` thành `!s`) và `.env.example`, có thể dồn vào một PR `chore` riêng
- [ ] Commit `CLAUDE.md` và file này lên nhánh `chore/add-claude-md`, mở PR rồi merge
- [ ] Ghi lại baseline: `uv run pytest -q --durations=5` → 162 pass; `test_bash_timeout` khoảng 5s
- [ ] Về máy cá nhân: clone repo, đặt `user.name`/`user.email` cho repo, chạy `uv sync` rồi `uv run pytest -q`

---

## PR 1 — Tính toàn vẹn của transcript

### #1 — ID tool call trùng giữa các lượt nên lời gọi mồ côi không được vá

- **Bất biến bị vi phạm:** *mỗi tool call trong transcript phải có đúng một kết quả đi kèm.* `cancel_pending_tool_calls` được viết để giữ bất biến này. Nhưng nó dựa vào một giả thiết ngầm: *ID của tool call là duy nhất trong toàn bộ transcript*. Giả thiết đó sai.
- **Nơi xảy ra:**
  - [`providers/gemini.py:249`](../src/tap/providers/gemini.py#L249) tạo `id=f"call_{i}_{fc.name}"`. ID này chỉ phụ thuộc vào vị trí trong *một* response và tên tool.
  - [`agent.py:106-118`](../src/tap/agent.py#L106-L118) gom tập `resolved` từ **toàn bộ** transcript.
- **Kịch bản (phản ví dụ):**
  1. Lượt 1: model gọi `read`, nhận ID `call_0_read`. Tool chạy xong, ID này vào tập resolved.
  2. Lượt 2: model lại gọi `read`, nhận **lại** ID `call_0_read`. Người dùng bấm Ctrl+C trong lúc tool đang chạy.
  3. `cancel_pending_tool_calls` thấy `call_0_read` đã nằm trong resolved (do lượt 1), nên không vá.
  4. Lượt 3: request gửi lên chứa một function_call không có function_response, và Gemini có thể trả `INVALID_ARGUMENT`.
  - **Bằng chứng:** script thử cho thấy sau Ctrl+C ở lượt 2, message cuối của transcript vẫn là `AssistantMessage` mang tool_call chưa có kết quả.
- **Vì sao test hiện có không bắt được:** các test đều chỉ có **một lượt**, tức chỉ kiểm trường hợp n = 1.
- **Khái niệm cần học:**
  - Generator trong Python: `yield`, `.send()`, `.close()`, và khi nào khối `finally` chạy.
  - `KeyboardInterrupt` là `BaseException`, không phải `Exception`, nên nó đi xuyên qua các khối `except Exception`.
  - Sự khác nhau giữa **định danh** (identity) và **vị trí** (position) của một đối tượng.
- **Gợi ý hướng** (nên làm cả hai, mỗi cái chặn lỗi ở một tầng):
  1. *Tầng Agent:* không cần nhìn toàn bộ transcript. Lời gọi mồ côi chỉ có thể nằm ở **message assistant cuối cùng có tool_calls**, cùng các kết quả đứng sau nó. Thử tự chứng minh vì sao các message assistant cũ hơn luôn đã đủ kết quả.
  2. *Tầng Provider:* tạo ID duy nhất. `types.FunctionCall` có trường `id`; nếu Gemini không trả về thì tự sinh, gợi ý dùng module `uuid`. `types.FunctionResponse` cũng có `id`, nên truyền vào để ghép kết quả theo ID.
- **Test cần viết** (viết trước và phải thấy **fail**): hai lượt, cả hai đều dùng ID `call_0_read`; lượt 2 có executor ném `KeyboardInterrupt`. Assert rằng mọi tool call đều có kết quả **theo vị trí**, xem thêm #1b.
- **Tiêu chí xong:** test mới pass, toàn bộ test cũ vẫn pass.
- [ ] Viết test tái hiện lỗi và thấy nó fail
- [ ] Sửa tầng Agent
- [ ] Sửa tầng Provider: ID duy nhất, truyền `id` vào `FunctionResponse`
- [ ] Thêm test cho provider: hai lần parse cho ra hai ID khác nhau
- **Ghi chú đã học được:**

### #1b — Fixture kiểm tra cũng mắc cùng lỗi

- **Vấn đề:** `assert_no_orphaned_tool_calls` trong [`tests/conftest.py:14-21`](../tests/conftest.py#L14-L21) dùng **đúng logic so ID** giống `cancel_pending_tool_calls`. Vì vậy dù có viết đúng kịch bản của #1, fixture này vẫn báo "không có lời gọi mồ côi".
- **Bài học:** đây là *vấn đề oracle*. Công cụ dùng để kiểm phải độc lập với giả thiết của code được kiểm; nếu cả hai cùng sai một kiểu thì test pass mà không chứng minh được gì.
- **Gợi ý:** viết lại fixture để kiểm **theo vị trí**. Sau mỗi message assistant có k tool call, phải có đúng k kết quả với ID khớp, đứng trước message assistant hoặc message user kế tiếp.
- [ ] Viết lại fixture, và kiểm rằng fixture mới **fail** trên code cũ
- **Ghi chú đã học được:**

### #7 — `/resume` không vá lời gọi mồ côi

- **Bất biến:** giống #1, nhưng lần này transcript đến từ file chứ không từ bộ nhớ.
- **Nơi xảy ra:** `_cmd_resume`, [`cli.py:329-345`](../src/tap/cli.py#L329-L345).
- **Kịch bản:** tiến trình bị kill khi tool đang chạy (đóng terminal, tắt máy), nên khối `finally` của harness **không kịp chạy**. File JSONL kết thúc bằng một assistant có tool_calls. Sau khi `/resume`, request đầu tiên sẽ lỗi.
- **Khái niệm:** khi nào `finally` chạy và khi nào không (bị kill bằng SIGKILL hoặc đóng cửa sổ thì không chạy).
- **Gợi ý:** gọi hàm vá ngay sau khi load messages. **Phải làm sau #1**, nếu không sẽ dính lỗi trùng ID.
- [ ] Test: tạo file JSONL dở dang → resume → assert transcript đã được vá
- [ ] Sửa `_cmd_resume`
- **Ghi chú đã học được:**

### (Tuỳ chọn) Thêm `tool_call_id` vào `ToolCallStartEvent`
- [ ] Khoảng 20 phút. Lớp xin phép và việc chạy tool song song sau này sẽ cần trường này.

---

## PR 2 — Timeout của `bash` không kill được tiến trình con

### #2

- **Bất biến bị vi phạm:** *một lệnh có timeout T phải kết thúc trong khoảng T giây.*
- **Nơi xảy ra:** [`tools/bash.py:92-110`](../src/tap/tools/bash.py#L92-L110), chỗ gọi `subprocess.run(..., shell=True, timeout=...)`.
- **Bằng chứng:** `test_bash_timeout` đặt `timeout=1` nhưng chạy mất **5.11s**. Với lệnh `python -m http.server` hay `npm run dev`, agent sẽ treo vĩnh viễn.
- **Cơ chế:**
  1. `shell=True` sinh ra cây tiến trình `python (tap) → cmd.exe → lệnh thật`.
  2. Khi hết giờ, `subprocess.run` chỉ kill **`cmd.exe`**.
  3. Lệnh thật vẫn sống và vẫn giữ đầu ghi của **pipe** stdout/stderr.
  4. `communicate()` đọc tới khi pipe đóng (EOF), mà pipe chỉ đóng khi lệnh thật chết, nên `communicate()` treo.
- **Khái niệm cần học** (phần này lạ nhất với nền toán, nên dành thời gian):
  - Process và PID; quan hệ cha–con; cây tiến trình.
  - Pipe và EOF: vì sao người đọc phải chờ *mọi* người ghi đóng pipe thì mới thấy EOF.
  - Process group và session (POSIX), signal `SIGTERM`/`SIGKILL`.
  - Trên Windows: không có signal kiểu POSIX; dùng `CREATE_NEW_PROCESS_GROUP` và `taskkill /F /T`.
- **Gợi ý hướng:** bỏ `subprocess.run`, tự quản lý `subprocess.Popen` rồi gọi `proc.communicate(timeout=...)`. Khi gặp `TimeoutExpired`, kill **cả cây** rồi gọi `communicate()` thêm một lần để dọn pipe. Nên tách riêng một hàm `_kill_tree(proc)` cho mỗi nền tảng.
- **Test:**
  - Sửa `test_bash_timeout` để assert thời gian chạy dưới 3s, đo bằng `time.monotonic()`.
  - Thêm test lệnh sinh tiến trình con ngủ lâu.
  - Thử tay với `python -m http.server`.
- [ ] Đọc và tự thử các khái niệm trên, ví dụ quan sát cây tiến trình bằng Task Manager hoặc `tasklist`
- [ ] Test thời gian chạy (phải fail trước khi sửa)
- [ ] Cài đặt cho Windows
- [ ] Cài đặt cho POSIX (khó test trên máy Windows; có thể nhờ CI hoặc WSL)
- [ ] Thử tay với một lệnh server
- **Ghi chú đã học được:**

---

## PR 3 — Blocklist của `bash`

### #4 — Vừa chặn nhầm vừa dễ lách, và README nói quá

- **Bất biến bị vi phạm:** README khẳng định *"filesystem access is confined to the project directory"*. Điều này sai: `bash` không bị giới hạn gì ngoài thư mục làm việc (cwd).
- **Nơi xảy ra:** [`tools/bash.py:23-51`](../src/tap/tools/bash.py#L23-L51) và README (mục Features, Design notes).
- **Bằng chứng:**
  - Bị chặn nhầm: `grep -rn "shutdown" src`.
  - Lọt qua: `rm -f -r`, `find . -delete`, `git clean -fdx`, `git reset --hard`, `shutil.rmtree`, `Remove-Item -Recurse`.
- **Khái niệm:**
  - So khớp chuỗi con khác với regex có ranh giới từ (`\b`).
  - **Mô hình mối đe doạ (threat model):** blocklist không bao giờ đầy đủ, vì có vô số cách viết khác nhau cho cùng một hành động. An toàn thật đến từ allowlist cộng với việc hỏi người dùng (Q1).
- **Gợi ý:** dùng regex với `\b`; bổ sung các mẫu còn thiếu; sửa README cho trung thực.
- [ ] Test dạng bảng với `pytest.mark.parametrize`, gồm cả lệnh phải chặn và lệnh phải cho qua
- [ ] Chuyển sang regex
- [ ] Sửa README
- **Ghi chú đã học được:**

---

## PR 4 — Các ca biên của `read` và `edit`

### #3 — Thông báo OVERSIZE sai đơn vị và thiếu offset tiếp theo
- **Nơi xảy ra:** [`tools/read.py:159`](../src/tap/tools/read.py#L159).
- **Bằng chứng:** in ra `has 2 chars`, nhưng 2 là số **dòng** (`file_len`). Thông báo cũng không có `offset=` nên model không biết đọc tiếp từ đâu.
- **Gợi ý:** làm theo định dạng của nhánh `MORE`; nếu dòng bị cắt là dòng cuối thì bỏ phần offset.
- [ ] Test → sửa
- **Ghi chú đã học được:**

### #5 — `apply_edits` bỏ sót các lần khớp chồng lên nhau
- **Bất biến:** *`old` khớp tại đúng một vị trí.*
- **Nơi xảy ra:** [`tools/edit.py:315`](../src/tap/tools/edit.py#L315); `str.count` chỉ đếm các lần khớp **không chồng nhau**.
- **Bằng chứng:** `"aa"` trong `"aaa"` có hai vị trí (0 và 1), nhưng `count` trả về 1, nên edit được áp dụng thay vì báo mơ hồ.
- **Gợi ý:** gọi `find` lần thứ hai, bắt đầu từ `first + 1`.
- [ ] Test → sửa
- **Ghi chú đã học được:**

### E — Mô tả tool `edit` lệch với schema
- **Nơi xảy ra:** [`tools/edit.py:155`](../src/tap/tools/edit.py#L155) nói `old_text`, trong khi schema là `edits[].old`/`edits[].new`, và class `Edit` không có `Field(description=...)`.
- **Khái niệm:** model chỉ "nhìn thấy" mô tả và JSON schema; nếu hai thứ này mâu thuẫn, model sẽ đoán sai tên trường.
- [ ] Sửa mô tả và thêm description cho từng trường
- [ ] Test: in `EditTool().input_schema` và kiểm có description

### F — Ghi file không nguyên tử
- **Bất biến:** *sau một lần ghi, file hoặc là bản cũ nguyên vẹn, hoặc là bản mới nguyên vẹn, không có trạng thái ở giữa.*
- **Nơi xảy ra:** `tools/write.py:53` và [`tools/edit.py:417`](../src/tap/tools/edit.py#L417). Mở file ở chế độ `"w"` sẽ xoá nội dung **ngay lập tức**, rồi mới ghi.
- **Khái niệm:** ghi nguyên tử bằng cách ghi ra file tạm rồi `os.replace`. Phải đặt file tạm **cùng thư mục** với file đích, vì đổi tên giữa hai ổ đĩa không còn nguyên tử. Trên Windows, `os.replace` lỗi nếu file đang bị chương trình khác mở.
- **Gợi ý:** viết helper dùng chung, ví dụ `tools/_fs.py: atomic_write(path, text)`, rồi gọi nó từ `write` và `edit`.
- [ ] Viết helper và test cho helper
- [ ] Dùng helper trong `write` và `edit`
- **Ghi chú đã học được:**

---

## PR 5 — Độ bền của provider

### #9 — Thông báo lỗi lọt vào transcript như lời của model
- **Bất biến:** *transcript chỉ chứa những gì model thực sự nói và những gì tool thực sự trả về.*
- **Nơi xảy ra:** [`agent.py:177-191`](../src/tap/agent.py#L177-L191) thêm message vào transcript **trước** khi kiểm `stop_reason == "error"`. [`providers/gemini.py:219-226`](../src/tap/providers/gemini.py#L219-L226) bỏ mất nội dung đã sinh khi gặp `MAX_TOKENS`.
- **Bằng chứng:**
  - Provider trả lỗi thì transcript thành `[User, Assistant(stop_reason=error)]`. Lượt sau, dòng `[Gemini blocked…]` được gửi lên với role `model`.
  - Provider ném exception hai lần thì transcript thành `[User, User]`: hai message user liền nhau, không có câu trả lời.
- **Đã kiểm trong SDK 2.17.0:** `FinishReason` có `MALFORMED_FUNCTION_CALL`, `UNEXPECTED_TOOL_CALL`, `TOO_MANY_TOOL_CALLS`, nhưng code chưa có thông báo riêng cho chúng.
- **Gợi ý:**
  1. Message lỗi chỉ phát ra thành event, không thêm vào transcript.
  2. Khi provider ném exception: cân nhắc gỡ `UserMessage` vừa thêm, hoặc ghi rõ cách xử lý trong docstring. Mỗi cách có được và mất gì?
  3. Thêm mô tả cho các finish reason mới.
  4. `MAX_TOKENS`: giữ phần text đã sinh để hiển thị, nhưng vẫn báo lỗi.
- **Lưu ý:** việc này đổi hành vi đang có test (`test_agent_provider_exception_yields_error_event`, các test trong `test_gemini_parse.py`), nên test cũ phải sửa theo, và sửa có chủ đích.
- [ ] Test cho từng điểm → sửa
- **Ghi chú đã học được:**

### #10 — Throttle cứng 10 RPM
- **Nơi xảy ra:** [`providers/gemini.py:52`](../src/tap/providers/gemini.py#L52); `cli.py` không truyền tham số này, và `Settings` không có.
- **Hậu quả:** mỗi lần gọi model cách nhau ít nhất 6s, nên một lượt 10 vòng mất khoảng 54s chỉ để chờ.
- **Khái niệm:** rate limiting phía client khác với retry khi server trả 429; mỗi cách có được và mất gì.
- **Gợi ý:** thêm `TAP_REQUESTS_PER_MINUTE` vào `Settings`, cập nhật `.env.example`, README và `/config` (mặc định theo Q2).
- [ ] Thêm setting, nối vào provider, kèm test (đã có `test_build_wires_thinking_budget` làm mẫu)
- **Ghi chú đã học được:**

### #11 — Retry không bắt lỗi mạng
- **Nơi xảy ra:** [`providers/gemini.py:104`](../src/tap/providers/gemini.py#L104) chỉ bắt `errors.APIError` và `TimeoutError`.
- **Đã kiểm:** `httpx.ReadTimeout` **không** phải lớp con của `TimeoutError`. Chuỗi kế thừa là `ConnectError → NetworkError → TransportError → RequestError → HTTPError`.
- **Khái niệm:** cây kế thừa exception; bắt lớp cha thì bắt được cả nhóm con. Bắt rộng quá cũng nguy hiểm.
- **Gợi ý:** bắt thêm `httpx.TransportError`; khai báo `httpx` trong `pyproject.toml` vì code import trực tiếp.
- [ ] Test: monkeypatch để client ném `httpx.ConnectError` hai lần rồi thành công; dùng lại cách giả `sleep` trong `test_provider_retry.py`
- **Ghi chú đã học được:**

---

## PR 6 — Session và CLI

### #6 — `/clear` không tạo file session mới, plan không được reset
- **Bất biến:** *nội dung `/resume` nạp lại phải đúng bằng transcript lúc thoát.*
- **Nơi xảy ra:** [`cli.py:426-429`](../src/tap/cli.py#L426-L429); `/new` và `/resume` cũng không đụng tới `plan_state`.
- **Bằng chứng:** chat "BEFORE CLEAR", rồi `/clear`, rồi chat "after clear". Khi resume, cả hai message đều quay lại.
- **Gợi ý:** theo Q3; thêm `PlanState.clear()` và gọi nó ở `/clear`, `/new` và `/resume`.
- [ ] Test → sửa
- **Ghi chú đã học được:**

### #8 — Session ID trùng trong cùng một giây, và không kiểm ID
- **Nơi xảy ra:** [`storage.py:429-446`](../src/tap/storage.py#L429-L446).
- **Bằng chứng:**
  - Gọi `new_session()` hai lần liên tiếp cho ra cùng ID và cùng file. Chạy `tap "..."` hai lần trong một script là dính.
  - `store.load("../evil")` đọc được file nằm **ngoài** thư mục session (path traversal).
- **Khái niệm:** va chạm ID (bài toán ngày sinh — tính thử với hậu tố 4 ký tự hex thì xác suất trùng là bao nhiêu); mode `"x"` khi mở file (tạo mới, báo lỗi nếu đã tồn tại); kiểm đầu vào bằng regex.
- **Gợi ý:** ID dạng `YYYYMMDD-HHMMSS-<hex ngẫu nhiên>`, vẫn sắp xếp đúng theo thời gian; tạo file bằng `open(path, "x")`; kiểm ID bằng regex trong `load` và `open_existing`; bỏ `sleep(1.1)` trong [`tests/test_storage.py:86`](../tests/test_storage.py#L86).
- [ ] Test → sửa
- **Ghi chú đã học được:**

---

## PR 7 — Prompt và dọn dẹp

### D — Prompt không có thông tin môi trường
- **Vấn đề:** model không biết OS, shell hay ngày hiện tại. Tool tên là `bash` nhưng trên Windows lại chạy `cmd.exe`.
- **Gợi ý:** thêm một khối `<environment>` gồm OS (`platform.system()`), shell thực tế, thư mục làm việc và ngày. Lưu ý `test_prompt.py` có thể đang so khớp chuỗi.
- [ ] Test → sửa

### H — Việc vặt
- [ ] Chuyển `pytest` từ `dependencies` sang nhóm `dev` trong `pyproject.toml`
- [ ] Khai báo `python-dotenv` và `httpx`, vì code import trực tiếp
- [ ] Dọn chuỗi tiếng Việt còn sót: `tools/plan.py:62`, `tools/_paths.py:47`, và comment trong một số file test
- [ ] README: sửa số test (158 → số thực tế); argparse: bỏ chữ "(v4)"
- [ ] CHANGELOG: thêm mục `[0.4.1]` liệt kê các bản sửa

---

## Điều kiện để chuyển sang nâng cấp

- [ ] Toàn bộ test pass; test suite chạy dưới 10s; `test_bash_timeout` dưới 3s
- [ ] Chạy tay một kịch bản thật: đọc file → sửa → chạy test → Ctrl+C giữa chừng → gõ tiếp → `/resume`
- [ ] Chốt Q1 và Q4

## Danh sách nâng cấp (sau đợt này, chưa ước lượng)

- Lớp xin phép người dùng cho `bash`, `write` và `edit` (bọc `tool_executor`)
- Quản lý context: đếm token, cắt kết quả tool cũ, compaction
- Streaming: đổi Protocol của provider để trả về delta
- Lưu plan vào session
- Provider thứ hai (OpenAI hoặc Anthropic)

---

## Nhật ký

| Ngày | Máy | Việc đã làm | Học được |
|---|---|---|---|
| 2026-11-17 | công ty | Lập kế hoạch; xác nhận lại lỗi #1–#11 bằng chạy thử; phát hiện #1b | — |

# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới.

## 1. Mục tiêu

Theo roadmap §20: Phase 0–4 xong hoàn toàn (Phase 4 còn thiếu mỗi Settings).
Phase 5 (Publishing) — "scaffold đầy đủ + mock provider" theo lựa chọn của
người dùng — đã xong: kiến trúc OAuth/quota/publish đầy đủ, test bằng
provider `mock` (không gọi YouTube/TikTok/Instagram thật, vì cần app OAuth
thật do người dùng tự đăng ký — chưa làm lượt này).

## 2. Những phần đã hoàn thành

**Phase 0–4 — đã xong, đã commit (LOCAL, chưa push theo yêu cầu).** Chi
tiết: [.claude/rules/dashboard.md](../rules/dashboard.md),
[.claude/rules/infra.md](../rules/infra.md).

**Publishing / Phase 5 (§6.17, §18.1, §18.3, §20) — MỚI phiên này.** Chi
tiết đầy đủ: [.claude/rules/publishing.md](../rules/publishing.md).

- `services/publishing/` (base/adapters/registry/quota) — config-driven
  đúng mẫu translation/TTS, chỉ có provider `mock` (chủ ý, theo lựa chọn
  scope của người dùng). `config/publishing/mock.json` dùng ĐÚNG số quota
  thật của YouTube (10000/1600 ≈ 6 video/ngày) dù không gọi mạng thật.
- `db/models.py::PlatformAccount` (token mã hoá qua `services/crypto.py`,
  Fernet) — bảng thứ 24 (`test_du_24_bang`).
- `workers/publishing/stage.py::PublishStage` — nối thật vào
  `PIPELINE_ORDER` (không còn `NotImplementedStage`). Chặn đúng thứ tự: QC
  phải PASS → account phải hợp lệ (tự refresh nếu hết hạn còn refresh_token)
  → còn quota hôm nay → mới publish thật, ghi `PublishingJob`, set
  `ai_disclosure=True`.
- `api/routes/publishing.py` — OAuth 3-legged THẬT (authorize→consent→
  callback, state CSRF chống replay), accounts/revoke, quota/history,
  publish-job. `mock` provider tự đóng vai "authorization server" (trang
  HTML riêng) nhưng đi qua đúng cơ chế redirect như nền tảng thật.
- Frontend: trang `/publish` (Publishing Calendar — kết nối account, quota,
  lịch sử) + `PublishPanel` nhúng vào Video Workspace (`/jobs/[id]`).
- **Bug thật bắt được khi test qua HTTP thật (không lộ ở unit test cùng
  session)**: SQLite đọc lại `DateTime(timezone=True)` qua session MỚI mất
  tzinfo → so sánh với `datetime.now(UTC)` ném `TypeError`. Sửa bằng
  `db/base.py::UTCDateTime` (TypeDecorator) áp cho MỌI cột datetime trong
  `db/models.py`, không chỉ chỗ vừa lộ ra — có test round-trip 2-session
  khoá lại fix (`test_utc_datetime.py`).
- **Đã xác nhận bằng trình duyệt thật (chrome-devtools MCP) toàn bộ luồng**:
  kết nối tài khoản (chọn platform → nhập tên → Kết nối → redirect qua
  backend → trang consent giả → Cho phép → quay lại dashboard, tài khoản
  hiện ra), Thu hồi tài khoản, và Publish bị chặn đúng khi QC chưa PASS
  (đúng §15) — cả qua curl lẫn qua UI thật.
- 15 test mới (`test_crypto.py`, `test_publishing_quota.py`,
  `test_publishing_stage.py`, `test_utc_datetime.py`).

## 3. Trạng thái hiện tại

- **238/238 test Python pass**. Frontend: `tsc --noEmit` sạch, `eslint`
  sạch, `next build` thành công (6 route: `/`, `/queue`, `/publish`,
  `/projects/[id]`, `/jobs/[id]`, `/_not-found`).
- **Lỗi đã biết, KHÔNG phải mới**: QC `background_retained` FAIL trên
  es-ES — hạn chế fixture tổng hợp (sine wave), không phải bug render.
- **Chưa commit**: toàn bộ code Phase 5 phiên này (services/publishing/,
  workers/publishing/stage.py, api/routes/publishing.py, db model +
  UTCDateTime fix, apps/web/src/app/publish/, PublishPanel, test mới, rule
  docs) — đã git add? CHƯA, đang chờ xác nhận.
- **Người dùng yêu cầu KHÔNG tự push code lên git** phiên này — chỉ commit
  local nếu được xác nhận, không `git push`.
- Nợ kỹ thuật khác (chi tiết: [.claude/rules/tech-debt.md](../rules/tech-debt.md)):
  `forced_align` xấp xỉ tuyến tính; `speech_rate_cps` chưa hiệu chuẩn cho
  `elevenlabs`/`openai_tts`; `render` chưa áp `FitStrategy.VIDEO_STRETCH`;
  chưa có render preset lẫn publishing preset (§14); `speaker_voices` chưa
  có cho `elevenlabs`; dry-run cost estimate (§17.1) chưa có; `onscreen_text`
  vẫn stub; Settings (Phase 4) chưa làm; publish chưa nối nền tảng thật nào.

## 4. Bước tiếp theo

1. **Xác nhận commit (LOCAL, không push) toàn bộ Phase 5** — đang chờ.
2. Roadmap §20 core (Phase 0–5) nay đã xong về mặt kiến trúc/scaffold. Lựa
   chọn kế tiếp: **Settings** (mảng cuối của Phase 4, không phụ thuộc gì
   khác); nối publish với **1 nền tảng thật** (YouTube dễ nhất — không cần
   audit như TikTok) nếu người dùng muốn tự tạo OAuth app; **Phase 6** (mở
   rộng: lip-sync, on-screen text, GPU tuning, regression tests); hoặc việc
   nhỏ nâng chất lượng còn tồn (dry-run cost §17.1, hiệu chuẩn
   `speech_rate_cps`, `FitStrategy.VIDEO_STRETCH`, render preset).
3. Nếu người dùng lấy được `HF_TOKEN`: `.venv/bin/pip install pyannote.audio`,
   export `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận diarize
   + multi-voice TTS chạy thật.

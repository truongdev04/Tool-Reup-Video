# Publishing (§6.17, §18.1, §18.3, Phase 5)

Config-driven đúng mẫu `services/providers/`/`services/tts/` (§2.2): thêm
nền tảng mới = 1 file JSON trong `config/publishing/` + 1 adapter trong
`services/publishing/adapters.py`, không sửa `workers/publishing/stage.py`
hay router.

- `services/publishing/base.py` — `PublishingProvider` (ABC: `authorize_url`/
  `exchange_code`/`refresh`/`publish` — OAuth 3-legged, khác hẳn 1 API key
  tĩnh của translation/TTS), `PublishingConfig`, `TokenSet`, lỗi
  `PublishingError`/`MissingOAuthCreds`.
- `services/publishing/adapters.py` — **chỉ có `mock`** ở lượt này (quyết
  định có chủ ý: "scaffold đầy đủ + mock provider trước, nối nền tảng thật
  là việc của lượt sau" — chưa có app OAuth thật của YouTube/TikTok/
  Instagram). `MockPublishingProvider`: "authorization server" và "upload
  API" đều do CHÍNH backend đóng vai (`api/routes/publishing.py::mock_consent`),
  không gọi ra ngoài — nhưng đi qua ĐÚNG luồng OAuth thật (state CSRF,
  redirect, callback, mã hoá token) nên test được toàn bộ cơ chế mà không
  cần tài khoản thật. Đặt `FAIL_MARKER` vào title để giả lập publish lỗi.
- `services/publishing/quota.py` — thuần, không I/O (§18.3: "nút thắt thật
  của batch là quota, không phải tốc độ render"). `config/publishing/mock.json`
  cố tình dùng ĐÚNG số thật của YouTube Data API
  (10.000 đơn vị/ngày, 1.600/lần `videos.insert` ≈ 6 video/ngày/project) dù
  adapter là mock — để quota manager được kiểm bằng số liệu thật.
- `workers/publishing/stage.py` (`PublishStage`) — nối vào `PIPELINE_ORDER`
  thật (không còn `NotImplementedStage`). Đọc `ctx.presets["publish_platform"/
  "publish_account_id"/"publish_title"/"publish_description"/"publish_hashtags"]`
  — cùng cơ chế `translation_provider`/`tts_provider` đã dùng cho translate/tts,
  KHÔNG có field riêng trên `Project`/`RenderJob`.
- `db/models.py::PlatformAccount` — token lưu MÃ HOÁ
  (`services/crypto.py`, Fernet) — không bao giờ đọc/ghi
  `access_token_encrypted`/`refresh_token_encrypted` trực tiếp.

## Thứ tự chặn trong `PublishStage.run()` — đừng đổi

1. Chưa cấu hình platform → **bỏ qua** (không needs_review) — hầu hết
   project không bật publishing, cùng nguyên tắc compose/diarize.
2. Chưa có `OutputFile` FINAL → `NonRetryableError` (không nên xảy ra nếu
   pipeline chạy qua `render`).
3. `qc_verdict != PASS` → needs_review, KHÔNG publish (§15: "chỉ publish khi
   QC = PASS và account authorization còn hợp lệ").
4. Không có account / account thu hồi & hết hạn không refresh được →
   needs_review.
5. Token hết hạn nhưng còn `refresh_token` → tự gọi `provider.refresh()`,
   cập nhật `PlatformAccount`, **đi tiếp** (không needs_review) — đúng "cơ
   chế refresh" §18.1.
6. Hết quota hôm nay → needs_review, không publish.
7. Gọi `provider.publish()` thật, ghi `PublishingJob` MỚI (xem dưới), set
   `OutputFile.ai_disclosure = True` (§18.2).

## Vì sao KHÔNG có `_clear_previous`

Khác mọi stage khác trong dự án: mỗi lần `publish` chạy thành công là MỘT
SỰ KIỆN THẬT trên nền tảng đích (video mới, id mới) — không phải artifact
tái tạo được. Xoá/ghi đè `PublishingJob` cũ sẽ mất lịch sử publish thật.
`cache_params` gồm platform/account/title/description/hashtags nên đổi bất
kỳ giá trị nào cũng tự bump cache — gọi lại với ĐÚNG tham số cũ thì cache-hit
(không publish trùng), đổi tham số thì publish lại (đúng ý "đăng lại với
tiêu đề khác").

## Bug thật bắt được khi test qua HTTP thật: `UTCDateTime`

**Không lộ ra ở unit test** (object tạo và dùng trong CÙNG session, SQLAlchemy
giữ nguyên attribute tz-aware trong bộ nhớ) — chỉ lộ khi có round-trip THẬT
qua SQLite từ một session MỚI, đúng luồng thật (request A ghi token, request
B đọc lại để kiểm hạn). SQLite lưu `DateTime(timezone=True)` được nhưng ĐỌC
LẠI trả về datetime NAIVE — so `PlatformAccount.is_usable_at`/
`VoiceConsent.is_valid_at` với `datetime.now(UTC)` (tz-aware) ném
`TypeError: can't compare offset-naive and offset-aware datetimes`. Sửa:
`db/base.py::UTCDateTime` (TypeDecorator tự gắn lại `tzinfo=UTC` khi đọc) áp
dụng cho MỌI cột `DateTime(timezone=True)` trong `db/models.py`, không chỉ
`PlatformAccount`. Xem `test_utc_datetime.py` — dựng lại đúng kịch bản hai
session để khoá fix, không lặp lại sai lầm "test trong cùng session".

## OAuth qua HTTP — state CSRF, `mock` "authorization server" giả

`api/routes/publishing.py`:
- `_oauth_states`/`_pending_labels`: dict trong bộ nhớ TIẾN TRÌNH API (không
  phải Celery worker), TTL 10 phút — đủ cho dev tool một tiến trình, KHÔNG
  sống sót qua restart hay nhiều worker process (xem giới hạn bên dưới).
- `authorize_url()` của adapter có thể trả đường dẫn TƯƠNG ĐỐI (`mock` làm
  vậy) — route tự resolve bằng `request.base_url`, không hard-code cổng
  (cổng dev có thể đổi, xem [infra.md](infra.md)).
- `mock_consent` là trang HTML tối thiểu do FastAPI render trực tiếp (không
  qua Next.js) — bấm "Cho phép" điều hướng THẬT về `redirect_uri` với `code`
  giả, đi qua ĐÚNG cơ chế redirect mà nền tảng thật sẽ dùng.
- Redirect cuối cùng về `http://localhost:3000/publish?connected=...` —
  cứng cổng 3000, cùng giả định dev-only như CORS trong `api/main.py`.

Đã xác nhận TOÀN BỘ luồng này bằng trình duyệt thật (chrome-devtools MCP):
chọn nền tảng → nhập tên → Kết nối → redirect qua backend → trang consent
giả → Cho phép → quay lại dashboard đúng URL, tài khoản mới xuất hiện, token
mã hoá không lộ ra API. Test luôn cả "Thu hồi" (revoke) và publish bị chặn
đúng khi QC fail.

## Giới hạn đã biết

- Chỉ có `mock` — chưa nối YouTube/TikTok/Instagram thật (cần app OAuth thật
  từ từng nền tảng, người dùng phải tự đăng ký). Thêm sau theo đúng mẫu
  adapter đã có.
- `PublishingConfig.needs_oauth_app`/`resolve_client_id`/`resolve_client_secret`
  đã viết sẵn cho provider thật cần `client_id_env`/`client_secret_env`
  nhưng CHƯA có provider nào dùng tới (chỉ `mock`, không cần OAuth app) —
  chưa test được đường đó.
- `_oauth_states` trong bộ nhớ tiến trình — không dùng được nếu chạy nhiều
  worker process/instance API phía sau load balancer (cần Redis nếu scale
  ngang, xem [infra.md](infra.md)).
- `PublishingJob.scheduled_at` có cột nhưng KHÔNG có tiến trình nào tự dispatch
  lúc tới giờ — publish luôn chạy NGAY khi gọi API, `scheduled_at` hiện chỉ
  là cột trống chưa dùng. "Publishing Calendar" ở dashboard là bảng lịch sử +
  quota, KHÔNG phải lịch đăng có giờ hẹn thật.
- **Publishing preset** (§14: platform + title_template + description_template
  + hashtags + schedule + ai_disclosure) CHƯA làm — người vận hành nhập
  title/description/hashtags trực tiếp mỗi lần publish qua `PublishPanel`,
  không có template tái dùng. Cùng loại nợ kỹ thuật với "render preset" đã
  ghi trong [tech-debt.md](tech-debt.md).
- Chưa test refresh token với provider CẦN `client_secret` thật (mock không
  cần) — luồng refresh chỉ xác nhận đúng về mặt cơ chế (state machine, mã
  hoá, cập nhật DB), chưa xác nhận với API thật của một nền tảng.

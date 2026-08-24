# Compose / branding (§6.14)

`compose` (`workers/compose/stage.py`) áp logo/watermark, CTA, intro/outro
theo thứ tự: **logo → CTA (trên video chính) → nối intro/outro**. Thứ tự này
có chủ ý — `duration_ms` cuối cùng của CTA phải tính từ điểm kết thúc của NỘI
DUNG CHÍNH, không phải điểm kết thúc sau khi đã có outro.

KHÔNG phụ thuộc locale nên `cache_scope=SOURCE`, chạy một lần cho mọi job
của cùng source. **CTA (và intro/outro) KHÔNG dịch theo locale** — quyết định
có chủ ý, giữ nguyên kiến trúc SOURCE-scope này thay vì đổi sang JOB-scope để
hỗ trợ CTA đa ngôn ngữ (việc đó để riêng, xem tech-debt.md).

Chưa có `Project.brand_profile_id` thì tự sinh brand placeholder đầy đủ
(logo + intro + outro + CTA mẫu qua `tests/fixtures/make_brand_assets.py`,
`BrandProfile.is_placeholder=True`) — để trục branding chạy được đầu-cuối mà
không cần asset thật. Asset placeholder lưu ở `Storage.shared_dir` (dùng
chung MỌI project) — **không phải per-project**: brand placeholder được TÁI
DÙNG theo tên giữa các project (tra theo `name`+`is_placeholder`, không theo
`project_id`), nên lưu per-project sẽ khiến project B đọc nhầm file vật lý
nằm trong thư mục project A một khi A bị dọn theo retention (§17.2). Đây là
lỗi đã phát hiện và sửa khi thêm intro/outro — logo trước đó cũng dính lỗi
này, chỉ chưa lộ ra vì ít khi 2 project chạy gần nhau đủ để thấy.

`render` kiểm tra `composed.mp4` có tồn tại theo quy ước path không, có thì
dùng, không thì fallback về video gốc — compose có thể bỏ qua hoàn toàn
(brand rỗng) mà không chặn pipeline.

## `cache_params` phải tự resolve brand, không chỉ đọc thô

`ComposeStage.cache_params` gọi `self._resolve_brand(ctx, project)` (không
chỉ đọc `project.brand_profile_id`) — **bắt buộc**, không phải tuỳ chọn. Lý
do: `cache_params` chạy TRƯỚC `run()` (kể cả khi sẽ cache hit). Nếu để
`run()` mới tạo brand placeholder, job locale đầu tiên tính `cache_params`
lúc brand CHƯA tồn tại, job locale thứ hai (cùng source, cùng pipeline
execution) tính `cache_params` lúc brand ĐÃ tồn tại — hai giá trị khác nhau,
input_hash lệch, compose chạy lại lần 2 dù `cache_scope=SOURCE` lẽ ra chỉ
chạy 1 lần. `_resolve_brand` vốn đã idempotent nên gọi từ `cache_params` an
toàn — `run()` gọi lại chỉ trúng fast-path có sẵn. Test chặn hồi quy:
`test_cache_params_on_dinh_giua_hai_locale_cung_project`.

Ngoài brand fingerprint, không có gì khác cần vào `cache_params` — compose
không đọc dữ liệu locale nào khác.

## Intro/outro phá đồng bộ audio + phụ đề nếu không bù — xem `services/branding.py`

Đây là lỗi nghiêm trọng nhất đã bắt được khi implement: nối intro/outro làm
**video dài hơn** audio đã tái dựng (§9) và SRT (§8.3) — cả hai vẫn tính theo
timeline NỘI DUNG CHÍNH, không biết gì về phần vừa nối thêm. Không bù thì:
- Audio (giọng đọc) phát ngay từ đầu, đè lên đoạn intro thay vì đợi tới khi
  nội dung chính bắt đầu; `-shortest` sau đó cắt luôn phần outro.
- Phụ đề hiện đè lên intro thay vì đợi đúng lúc lời thoại thật bắt đầu.

`services/branding.py::resolve_intro_outro_durations(ctx)` đọc lại (không
suy luận riêng) đúng field `BrandProfile` mà compose đã dùng, trả
`(intro_ms, outro_ms)`. `render` dùng để:
1. Dịch audio tới sau `intro_ms` (`adelay`) rồi đệm lặng khớp đúng độ dài
   video cuối (`apad=whole_dur=`) — xem `_audio_sync_filter`.
2. Viết lại SRT với mọi cue dịch thêm `intro_ms` trước khi burn — xem
   `_shifted_srt_path`. SRT gốc (chưa dịch) vẫn giữ nguyên, không sửa tại
   chỗ — file dịch là bản phái sinh riêng ở thư mục render.

`qc` dùng CÙNG hàm để: cộng `total_ms` vào `expected_duration_ms` của
`check_output_playable` (không thì QC FAIL nhầm mọi video có intro/outro vì
"thời lượng lệch quá xa so với nguồn"), và dịch điểm lấy mẫu của
`check_background_retained` theo `intro_ms` (không thì đo nhầm đoạn nằm
trong intro thay vì khoảng lặng thật của nội dung chính).

**Nguyên tắc chung khi sửa `render`/`qc`:** nếu code đọc `TranslationUnit`/
`SubtitleCue`/`SegmentTiming` (timestamp theo timeline nội dung chính) rồi
lấy mẫu/so khớp trực tiếp trên **video cuối cùng đã render**, phải cộng
`intro_ms`. Nếu chỉ so sánh các mốc đó VỚI NHAU (như `check_cue_overlap`),
không cần — offset như nhau cho mọi mốc không đổi kết quả so sánh tương đối.

## `prepare_clip_for_concat` — SAR, không chỉ resolution/fps

Lỗi thứ hai đã bắt được khi test bằng pipeline thật: filter `concat` từ chối
nối các clip dù đã `scale`+`pad` khớp đúng resolution/fps — SAR (sample
aspect ratio) lệch nhau kiểu `1:1` vs `18221:18225`. Sửa bằng `setsar=1`
trong CHÍNH filter chain đó, và ép **cả clip chính** (không chỉ intro/outro)
qua cùng filter này trước khi `concat_clips` — không có clip nào "thoát"
chuẩn hoá. Xem `services/compose_video.py::prepare_clip_for_concat`.

Xem [caching.md](caching.md) mục 4 cho câu chuyện `STAGE_DEPENDENCIES` từng bị
lệch khỏi implementation thật của stage này (vẫn đúng — compose không phụ
thuộc stage nào, kể cả sau khi thêm CTA/intro/outro).

# Compose / branding (§6.14)

`compose` (`workers/compose/stage.py`) chỉ áp logo/watermark — KHÔNG phụ thuộc
locale nên `cache_scope=SOURCE`, chạy một lần cho mọi job của cùng source.
Chưa có `Project.brand_profile_id` thì tự sinh brand placeholder (logo tổng
hợp qua `tests/fixtures/make_brand_assets.py`, `BrandProfile.is_placeholder=True`)
— để trục branding chạy được đầu-cuối mà không cần asset thật. `render` kiểm
tra `composed.mp4` có tồn tại theo quy ước path không, có thì dùng, không thì
fallback về video gốc — compose có thể bỏ qua (brand không có logo) mà không
chặn pipeline.

Xem [caching.md](caching.md) mục 4 cho câu chuyện `STAGE_DEPENDENCIES` từng bị
lệch khỏi implementation thật của stage này.

# Storage

`services/storage.py` — artifact **không** phụ thuộc locale nằm ở cấp project
(`source`, `analysis`, `separated`, `transcript`) để cache dùng chung giữa các
locale; artifact phụ thuộc locale nằm dưới `jobs/{job_id}/`. Đây là chỗ lệch có
chủ ý so với layout phẳng của §12, vốn sẽ khiến bản ES và JA ghi đè nhau.

`RETENTION_DAYS` phải phủ hết mọi `ArtifactKind` (có test chặn).

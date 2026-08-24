# Diarize (§6.5)

`workers/diarization/assign.py` (thuần — overlap-matching giữa lượt nói và
`stt_segment`, không I/O) → `services/diarization_pyannote.py` (gọi
`pyannote.audio` thật) → `workers/diarization/stage.py` (đọc DB, ghi
`Speaker`/`STTSegment.speaker_id`). Cùng mẫu tách thuần/I-O như [qc.md](qc.md).

## Bỏ qua khi thiếu token, KHÔNG `NonRetryableError`

Đây là chỗ lệch có chủ ý so với [coding-style.md](coding-style.md) ("thiếu cấu
hình → `NonRetryableError`"). Trước khi stage này tồn tại, `diarize` là
`NotImplementedStage` — mọi `STTSegment.speaker_id` mãi mãi `None`, và
`segment_planner`/`translation`/`tts` đã coi `speaker=None` là "một speaker
duy nhất" từ đó tới giờ. Bắt `pyannote.audio` + `HF_TOKEN` (model gated, phải
accept điều khoản trên HuggingFace) mới cho pipeline chạy được sẽ là một
regression. Nên: thiếu thư viện hoặc token → `DiarizationUnavailable` →
stage trả `succeeded` kèm `output_ref={"skipped": True, ...}` và giải thích
trong `note`, đúng nguyên tắc "có thể bỏ qua, không chặn pipeline" mà
`compose`/`render` đã áp dụng cho branding thiếu asset thật (xem
[compose.md](compose.md)).

`HF_TOKEN` là tên biến môi trường CHUẨN của huggingface_hub — đọc thẳng, không
đi qua `api_key_env` kiểu JSON như [providers.md](providers.md)/TTS, vì đó là
quy ước cho nhiều provider cùng lựa chọn; ở đây chỉ có một backend.

## Cache

`cache_scope=SOURCE` (không phụ thuộc locale, giống `stt`) — nhưng
`cache_params` vẫn phải override để đưa `diarization_model` vào key, nếu
không đổi model sẽ không bump cache (xem [caching.md](caching.md) mục 2, cùng
lý do STT override để bắt đổi Whisper model).

## Idempotency

`_clear_previous` phải NULL `stt_segments.speaker_id` TRƯỚC rồi mới xoá
`Speaker` — thứ tự ngược lại vỡ FK. Chạy `_clear_previous` cả trên đường "bỏ
qua" (không chỉ đường thành công) để tránh lệch: `note` báo "bỏ qua" nhưng DB
vẫn còn `Speaker` của lần chạy trước (khi trước đó có token, giờ bị thu hồi).

## Multi-voice TTS theo speaker

`Speaker.voice_mapping` ĐÃ được nối dây — xem `workers/tts/voice_assignment.py`
và `TTSStage._voice_assignment` (`providers.md`). `diarize` chỉ cần gán đúng
`speaker_id`; việc chọn giọng theo speaker là trách nhiệm của `tts`, không
phải của stage này — đúng ranh giới contract (mỗi stage một việc, §11.1).

Giới hạn hiện tại: `speaker_voices` (giọng phụ) trong `config/tts/*.json` mới
điền cho `macos_say` (en-US, fr-FR — các locale còn lại của `say` không có
giọng phụ AN TOÀN, xem providers.md) và `openai_tts` (mọi locale, giọng cố
định dùng chung). `elevenlabs` chưa có — cần voice ID thật từ tài khoản, không
thể tự bịa.

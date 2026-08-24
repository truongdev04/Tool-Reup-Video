# Provider LLM và TTS

Thêm provider mới **không phải sửa code** — thả một file JSON. Dịch:
`apps/api/config/providers/`, 3 giao thức (`services/providers/adapters.py`):
`openai_compatible` (phủ OpenAI, OpenRouter, 9Router, Groq, DeepSeek, Ollama,
LM Studio, vLLM...), `anthropic`, `gemini`, cộng `mock` cho test. TTS:
`apps/api/config/tts/`, tương tự (`services/tts/adapters.py`):
`macos_say` (local), `elevenlabs`, `openai_tts`.

API key chỉ đọc từ biến môi trường tại thời điểm gọi. Không lưu DB, không log.

Tốc độ đọc (`speech_rate_cps`) nằm trong config của TỪNG provider TTS, không
phải locale preset — đo bằng `scripts/calibrate_speech_rate.py`. Đổi provider
TTS thì phải đo lại.

## Multi-voice theo speaker (§6.5, §6.9)

`TTSConfig.voices[locale]` là giọng MẶC ĐỊNH (speaker đầu tiên/duy nhất).
`TTSConfig.speaker_voices[locale]` là danh sách giọng PHỤ cho speaker thứ 2
trở đi khi `diarize` gán được nhiều người nói — xem
`workers/tts/voice_assignment.py` và [diarization.md](diarization.md). Rỗng
(mặc định) = mọi speaker vẫn dùng chung một giọng, không phải lỗi.

Khi thêm/sửa `speaker_voices` cho `macos_say`: chỉ dùng voice PLAIN NAME (vd.
`Fred`, `Kathy`) — kiểm bằng `say -v '?'` trước khi thêm. Nhiều giọng `say`
chỉ tồn tại dưới tên gắn kèm ngôn ngữ hiển thị hệ thống (vd. `Eddy (Tiếng Tây
Ban Nha (Tây Ban Nha))`) — tên đó đổi theo ngôn ngữ macOS đang set nên KHÔNG
đưa vào config chung (sẽ vỡ trên máy khác). Vì vậy phần lớn locale của
`macos_say` (es-ES, ja-JP, vi-VN...) chưa có giọng phụ an toàn — chấp nhận
fallback "mọi speaker chung giọng" cho tới khi có provider khác hoặc cài thêm
voice pack, không tự bịa tên giọng chưa kiểm chứng.

`registry.load_config` chặn field lạ trong JSON (`unknown = set(data) -
set(TTSConfig.__dataclass_fields__)`) — thêm field mới vào `TTSConfig` trước,
đừng thêm thẳng vào JSON rồi mới sửa dataclass sau.

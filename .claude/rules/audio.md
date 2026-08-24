# Tái dựng audio (§9)

Track cuối là `TTS + background gốc`, **không phải thay thế**. Demucs tách ra
`background.wav` và phải giữ lại — thay nguyên track audio bằng TTS là mất sạch
nhạc nền, tiếng động và không khí video gốc.

`timeline_assembly` đặt mỗi `tts_chunk` tại **vị trí tuyệt đối** `unit.start_ms`
trong track dài bằng cả video (`services/audio_timeline.py`), không nối đuôi
nhau — nhờ vậy khoảng lặng và các mốc hình ảnh vẫn đúng chỗ. `render` trộn
track đó với `background.wav` rồi chuẩn hoá bằng **loudnorm hai lượt**
(`services/audio_mix.py`) — một lượt cho kết quả không ổn định giữa các file.

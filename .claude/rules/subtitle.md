# Nguyên tắc bất biến về subtitle (§8.3)

**Subtitle luôn sinh từ timestamp của audio sẽ phát, không bao giờ từ audio
nguồn.** Cột `subtitle_cues.from_forced_alignment` là cờ để QC kiểm chứng bằng
dữ liệu thay vì bằng mắt (xem [qc.md](qc.md)).

`forced_align` (`workers/forced_align/aligner.py`) KHÔNG dùng WhisperX/MFA như
§8 đề xuất — dùng chính mlx-whisper chạy lại trên audio TTS để lấy ranh giới
đoạn (nơi có khoảng lặng thật), rồi rải ký tự bản dịch vào đó theo tỉ lệ. Đây
là xấp xỉ tuyến tính có neo bằng audio thật, không phải alignment cấp phoneme.
Lý do: WhisperX/MFA cần model CTC riêng từng ngôn ngữ, phủ yếu các locale mục
tiêu (ja/vi/ar). Cách này không phụ thuộc ngôn ngữ.

**cps_max là ràng buộc MỀM khi TTS đọc nhanh hơn ngưỡng đọc** — TTS thường đọc
nhanh hơn tốc độ đọc thoải mái của phụ đề. `workers/subtitle/splitter.py` chỉ
tách cue vì lý do CPS sau khi cue đã đạt `min_cue_ms`; nếu không, giọng đọc
nhanh hơn `cps_max` một chút (rất hay gặp) sẽ khiến MỌI cặp từ liên tiếp "vượt
ngưỡng", vỡ vụn thành cue 1 từ nhấp nháy suốt video.

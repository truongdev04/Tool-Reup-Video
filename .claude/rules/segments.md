# Bốn tầng segment (§5)

Đây là điểm kiến trúc quan trọng nhất và dễ hiểu nhầm nhất. Không có bảng
`segments` gộp — bốn tầng cắt đoạn khác nhau, nối bằng `segment_links` (N:M):

| Tầng | Bảng | Cắt theo |
|---|---|---|
| 1 | `stt_segments` | khoảng lặng — vụn, hay cắt giữa câu |
| 2 | `translation_units` | câu/ý trọn vẹn — thiếu ngữ cảnh là dịch sai |
| 3 | `tts_chunks` | ngữ điệu tự nhiên — mỗi chunk là **một file audio riêng** |
| 4 | `subtitle_cues` | giới hạn đọc — CPS, số dòng, min/max duration |

`workers/segment_planner/planner.py` là module thuần (không API, không DB) phụ
trách gộp/tách giữa các tầng.

Điều kiện bắt buộc để partial re-run hoạt động: **mỗi `tts_chunk` phải là một
file riêng có địa chỉ**, và composition là bước ghép file, không phải một lệnh
FFmpeg khổng lồ chạy một lần.

# Quyết định cần chốt trước Phase 1

Theo dõi các quyết định mở ở kế hoạch §23. Cập nhật trạng thái khi chốt xong —
đừng xoá dòng, chỉ đổi trạng thái, để giữ lịch sử vì sao chọn phương án đó.

| # | Quyết định | Khuyến nghị trong kế hoạch | Trạng thái | Ghi chú |
|---|-----------|----------------------------|-----------|---------|
| 1 | Lip-sync có vào MVP không? | Không — đưa xuống Phase 6 | ⬜ Mở | |
| 2 | Chạy local hay thuê GPU? | Local trên Mac (whisper.cpp + videotoolbox) cho Phase 0–2; thuê GPU chỉ khi bật lip-sync | ⬜ Mở | |
| 3 | Provider TTS nào? | Abstraction từ đầu; benchmark 2–3 provider trên cùng 1 clip mẫu | ⬜ Mở | |
| 4 | Bao nhiêu locale cho MVP? | 2 locale khác hệ chữ (vd. Tây Ban Nha + Nhật) | ⬜ Mở | |
| 5 | N video riêng hay YouTube multi-audio-track? | Đánh giá API YouTube trước khi xây Phase 5 | ⬜ Mở | |

Trạng thái: ⬜ Mở · 🟡 Đang cân nhắc · ✅ Đã chốt

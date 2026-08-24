# Quy ước chung của dự án

## Ngôn ngữ

Toàn bộ tài liệu, comment, docstring, thông báo lỗi và commit message trong dự án
này viết bằng **tiếng Việt**. Giữ nguyên quy ước đó khi thêm code mới.

## Kế hoạch kiến trúc là nguồn chân lý

[docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md](../../docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md)
là tài liệu thiết kế đầy đủ. Code tham chiếu tới nó bằng ký hiệu mục (`§7.2`,
`§11.3`, `§16`...) trong docstring và comment.

**Đọc mục liên quan trước khi sửa một module**, và giữ tham chiếu `§` khi viết
code mới — đó là cách người đọc sau biết quyết định này đến từ đâu. Khi phải làm
khác kế hoạch, ghi rõ lý do ngay tại chỗ lệch (xem các ví dụ trong
`services/storage.py` và `core/orchestrator.py`).

Quyết định còn mở nằm ở [docs/decisions.md](../../docs/decisions.md).

## Commit

Commit message tiếng Việt, giải thích **vì sao** chứ không chỉ *cái gì*. Khi sửa
một lỗi thiết kế, ghi lại lỗi đó là gì và tại sao cách cũ sai — các commit hiện
có trong repo là mẫu tham khảo.

Kết bằng:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

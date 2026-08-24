# Duration Fitting (§7)

Bài toán khó nhất của dubbing. `workers/duration_fit/fitter.py` là module thuần
áp thang 4 chiến lược theo đúng thứ tự: dịch có ràng buộc → ăn khoảng lặng →
chỉnh tempo (0,92–1,08) → co giãn hình. Không chiến lược nào đủ thì đánh dấu
manual review, **không ép bừa**.

`decide()` nhận `cumulative_drift_ms` và nhắm khung `target - cumulative_drift`.
Xét từng đơn vị độc lập là sai: mỗi đơn vị lệch 240ms đều nằm trong dung sai
10%, nhưng 8 đơn vị dồn lại vượt xa ngưỡng 300ms của DoD §21.

# Cache — phần dễ làm sai nhất

Ba cơ chế chồng lên nhau trong `Orchestrator` (xem trước [stage-contract.md](stage-contract.md)
để biết stage giao tiếp qua đâu):

1. **Cache key nối chuỗi.** Key của một stage gồm `(input_hash, output_digest)`
   của các stage upstream. Dùng **cả hai** là cố ý: `output_digest` bắt trường
   hợp nội dung đổi (sửa câu dịch); `input_hash` bắt trường hợp một stage trả
   output hằng số — loại stage đó sẽ nuốt thay đổi từ upstream và âm thầm phá
   vỡ invalidation của toàn bộ downstream.

2. **`CacheScope`.** Stage `SOURCE` (`ingest`, `analyze`, `separate`, `stt`)
   không phụ thuộc locale nên mọi bản ngôn ngữ dùng chung kết quả. Stage `JOB`
   giới hạn trong phạm vi job vì `output_ref` trỏ tới bản ghi của chính job đó.

   **Khai `CacheScope.SOURCE` thì `cache_params` phải BỎ locale.** Lớp cơ sở đã
   xử lý, nhưng nếu override `cache_params` thì đừng thêm locale vào — kèm vào
   là cache_scope mất tác dụng dù khai báo đúng, và sai lầm lan xuống cả chuỗi.
   `test_stage_source_scope_cho_hash_giong_nhau_moi_locale` chặn regression này.

3. **Bump `config_version`** trong `core/config.py` để vô hiệu hoá toàn bộ cache.

4. **`STAGE_DEPENDENCIES` phải khớp với dữ liệu stage THẬT SỰ đọc, không phải
   sơ đồ ban đầu trong kế hoạch.** `__upstream__` của cache key được suy ra từ
   graph này (không phải từ code thật của stage), nên graph sai là cache sai
   mà không có lỗi runtime nào báo. Lỗi thật đã xảy ra: `compose` được implement
   lại (chỉ áp logo, không đọc `timeline_assembly`/`subtitle` như sơ đồ gốc)
   nhưng graph vẫn giữ nguyên phụ thuộc cũ — khiến `CacheScope.SOURCE` của nó
   vô nghĩa (cache key bị nhiễm theo locale dù bản thân stage không dùng dữ
   liệu đó). Sửa: cập nhật graph khớp implementation thật, và không dựa vào
   một stage "mang hộ" phụ thuộc của downstream — `render` phải khai TRỰC TIẾP
   mọi thứ nó đọc (`compose`, `timeline_assembly`, `subtitle`), không dựa vào
   `compose` mang hộ hai cái sau. Khi đổi dữ liệu một stage đọc, LUÔN kiểm tra
   lại `STAGE_DEPENDENCIES` của chính nó có còn đúng không.

Nguyên tắc khi phân vân: cache sai thì xuất ra video có audio cũ mà không ai
biết; cache trượt thì chỉ tốn thêm thời gian. **Luôn nghiêng về chạy lại.**

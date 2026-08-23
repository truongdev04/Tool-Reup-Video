# KẾ HOẠCH PHÁT TRIỂN TOOL — VIDEO LOCALIZATION & AUTOMATION

**Bản kiến trúc v3.0** — từ một video gốc tạo nhiều phiên bản ngôn ngữ và thương hiệu

> **Mục tiêu:** xây dựng công cụ nội bộ xử lý batch, kiểm soát chất lượng, quản lý chi phí
> và xuất bản theo quy trình có thể mở rộng.

---

## 0. Thay đổi so với v2

Bản v2 đúng ở tầng kiến trúc nhưng thiếu phần **nghiệp vụ media nằm giữa các module**.
v3 giữ nguyên toàn bộ kiến trúc v2 và bù các mắt xích còn thiếu.

| # | Thay đổi | Loại | Lý do |
|---|----------|------|-------|
| 1 | Thêm **Duration Fitting Engine** (§7) | Chặn MVP | Thời lượng đọc lệch 15–35% giữa các ngôn ngữ; v2 không có bước ép khớp khung hình |
| 2 | Thêm **Forced Alignment** trước subtitle (§8) | Chặn MVP | v2 sinh subtitle từ timestamp audio *nguồn*, trong khi người xem nghe audio *mới* |
| 3 | Tách **segment thành 4 tầng** (§5) | Chặn MVP | Một bảng `segments` dùng chung cho 4 loại đơn vị khác nhau sẽ khoá cứng chất lượng |
| 4 | Kéo **data model + stage contract lên Phase 1** (§20) | Chặn MVP | v2 để hạ tầng ở Phase 3 → Phase 3 phải viết lại Phase 1 |
| 5 | Thêm **Segment Planner** (§6.6) | Quan trọng | Chủ sở hữu của việc gộp/tách segment giữa các tầng |
| 6 | Thêm **On-screen Text Localization** (§6.12) | Quan trọng | v2 phát hiện `text-on-screen` nhưng không module nào dùng kết quả |
| 7 | Thêm **Approval Gates + Partial Re-run** (§11) | Quan trọng | v2 nói "manual review" nhưng không định nghĩa; sửa 1 câu không được render lại cả video |
| 8 | Thêm **Audio Reconstruction** tường minh (§9) | Quan trọng | Phải trộn `TTS + background gốc`, không thay nguyên track |
| 9 | Thêm **ước tính chi phí dry-run** (§17) | Nên có | v2 chỉ chặn *khi đang chạy*, không cảnh báo *trước khi* batch khởi động |
| 10 | Thêm **AI disclosure + voice consent** (§18) | Nên có | Nghĩa vụ công bố nội dung tổng hợp; biến ràng buộc pháp lý thành dữ liệu |
| 11 | Soi chiếu **stack với macOS + license model** (§13) | Quan trọng | Lip-sync CUDA-only; Wav2Lip là license phi thương mại |
| 12 | +5 bảng DB, mở rộng QC checklist và DoD | Quan trọng | Hệ quả của các thay đổi trên |

---

## 1. Mục tiêu hệ thống

Hệ thống nhận một video nguồn mà người dùng có quyền sử dụng, phân tích nội dung, dịch/localize
sang một hoặc nhiều ngôn ngữ, tạo giọng đọc mới, đồng bộ khẩu hình khi phù hợp, tạo phụ đề,
áp branding và render thành các video đầu ra độc lập.

- 1 video nguồn → nhiều phiên bản ngôn ngữ.
- Giữ nguyên hình ảnh nền hoặc tái biên tập một phần theo template.
- Hỗ trợ voice/TTS, subtitle, logo/branding, intro/outro, CTA và metadata.
- Chạy từng video hoặc batch hàng chục/hàng trăm video.
- Có hàng đợi, retry, cache, QC, logging và theo dõi chi phí.
- Publishing là module riêng, ưu tiên API/OAuth chính thức.

**Ràng buộc chất lượng (mới ở v3):** output chỉ được coi là hợp lệ khi
audio khớp hình trong ngưỡng cho phép, subtitle khớp audio *mới*, và nhạc nền gốc còn nguyên.
Ba điều này là tiêu chí nghiệm thu, không phải tính năng tuỳ chọn.

**Lưu ý phạm vi:** công cụ tập trung vào localization, biên tập và tạo phiên bản nội dung mới.
Không thiết kế các tính năng nhằm né Content ID, hệ thống phát hiện bản quyền hoặc cơ chế
thực thi của nền tảng.

---

## 2. Nguyên tắc kiến trúc

> Đưa lên đầu tài liệu vì đây là phần chi phối mọi quyết định bên dưới.
> Nếu giữ đúng 9 nguyên tắc này, mọi thiếu sót phát sinh đều vá được mà không phải viết lại.

1. Mọi module có input/output contract rõ ràng.
2. Không hard-code provider, voice, language, logo hoặc subtitle style vào source code.
3. Pipeline phải chạy lại được **từng stage**, không phải chạy lại toàn bộ.
4. Mọi kết quả đắt tiền phải được cache.
5. Mọi output phải có source/job lineage để truy vết.
6. Phân tách UI, API, workers và storage để scale độc lập.
7. Ưu tiên ổn định, quan sát được và khả năng rollback hơn tối đa tính năng ở bản đầu.
8. **(mới)** Sửa một segment chỉ được kích hoạt chạy lại đúng segment đó và remux — không encode lại toàn bộ.
9. **(mới)** Subtitle luôn sinh từ timestamp của audio **sẽ phát**, không bao giờ từ audio nguồn.

---

## 3. Kiến trúc tổng thể

Mô hình job-based pipeline: mỗi bước là một worker có input/output chuẩn hoá.
Cho phép retry từng bước, cache kết quả và mở rộng GPU workers độc lập.

```
FRONTEND (React / Next.js)
        |
API (FastAPI)
        |
PostgreSQL  <->  Redis / Job Queue
        |
WORKERS
 |- Import / Analyze
 |- Audio Separation / Processing
 |- STT / Diarization
 |- Segment Planner          <- MỚI
 |- Translation / Localization
 |- Duration Fitting         <- MỚI
 |- TTS / Voice
 |- Forced Alignment         <- MỚI
 |- Timeline Assembly        <- MỚI
 |- Subtitle
 |- On-screen Text           <- MỚI
 |- Lip-sync
 |- Composition / Render (FFmpeg)
 |- QC
 |- Publishing
        |
Storage (Local / S3-compatible)
        |
Final Outputs + Analytics
```

---

## 4. Luồng xử lý chuẩn

```
import -> analyze -> separate -> stt+diarize -> [segment planner] -> translate
   -> [duration fit] -> tts -> [forced align] -> [timeline assembly]
   -> subtitle -> lipsync -> compose -> render -> qc -> publish
```

| # | Stage | Mô tả | Mới |
|---|-------|-------|-----|
| 1 | `import` | Nhập video, checksum, metadata, ghi nhận quyền sử dụng | |
| 2 | `analyze` | Duration, resolution, FPS, codec, scenes, face, on-screen text, số speaker | |
| 3 | `separate` | Demucs tách vocals / background (nhạc nền + tiếng động) | |
| 4 | `stt` + `diarize` | Transcript, word-level timestamps, speaker ID | |
| 5 | **`segment_plan`** | Gộp STT segment thành đơn vị dịch trọn nghĩa | ✅ |
| 6 | `translate` | Dịch theo ngữ cảnh + glossary + style guide + **budget độ dài** | |
| 7 | **`duration_fit`** | Ép thời lượng đọc khớp khung hình theo 4 chiến lược | ✅ |
| 8 | `tts` | Sinh audio từng segment thành **file riêng có địa chỉ** | |
| 9 | **`forced_align`** | Lấy lại word-timestamp trên chính audio mới | ✅ |
| 10 | **`timeline_assembly`** | Ghép các file audio segment theo timeline, đo drift tích luỹ | ✅ |
| 11 | `subtitle` | Tách cue từ timestamp mới, áp CPS / số dòng / safe area | |
| 12 | `onscreen_text` | OCR → gắn cờ (MVP) hoặc inpaint + overlay (sau MVP) | ✅ |
| 13 | `lipsync` | Đồng bộ khẩu hình nếu bật và nguồn phù hợp | |
| 14 | `compose` | Logo, caption, CTA, intro/outro, audio mix, framing | |
| 15 | `render` | FFmpeg encode theo output preset | |
| 16 | `qc` | Kiểm tra tự động; Pass → lưu final, Fail → retry hoặc manual review | |
| 17 | `publish` | Upload / schedule nếu bật publishing | |

---

## 5. Mô hình segment 4 tầng

> **Đây là thay đổi cấu trúc quan trọng nhất của v3.** v2 dùng chung một khái niệm "segment"
> cho toàn pipeline. Thực tế bốn tầng cắt đoạn không trùng nhau — ép chung một bảng
> sẽ khoá cứng chất lượng ở mọi bước sau.

| Tầng | Bảng | Cắt theo | Đặc điểm |
|------|------|----------|----------|
| 1 | `stt_segments` | Khoảng lặng trong audio | Vụn, thường cắt giữa câu |
| 2 | `translation_units` | Câu / ý trọn vẹn | Gộp từ nhiều STT segment; thiếu ngữ cảnh là dịch sai |
| 3 | `tts_chunks` | Ngữ điệu tự nhiên | Để giọng đọc không cụt giữa chừng |
| 4 | `subtitle_cues` | Giới hạn đọc | ≤ 2 dòng, CPS hợp lý, min/max duration |

Bốn tầng nối với nhau bằng bảng mapping **N:M** (`segment_links`), không phải khoá ngoại 1:1.

### Quy tắc Segment Planner

```
STT segments (vụn)
   |  gộp: nối các segment tới khi gặp dấu kết câu,
   |       tối đa ~250 ký tự, không vượt ranh giới speaker
   v
translation_units  --> đưa vào LLM kèm 1-2 unit trước/sau làm ngữ cảnh
   |
   |  tách: theo dấu câu và cụm ngữ pháp của NGÔN NGỮ ĐÍCH
   v
tts_chunks  --> mỗi chunk là 1 file audio riêng
   |
   |  tách lại từ word-timestamp của audio MỚI (sau forced align)
   v
subtitle_cues
```

**Giới hạn subtitle theo ngôn ngữ** (cấu hình trong locale preset, không hard-code):

| Nhóm ngôn ngữ | Ký tự/dòng | CPS tối đa | Ghi chú |
|---------------|-----------|------------|---------|
| Latin (EN, ES, FR, DE, VI...) | 37–42 | 17–20 | Ngắt theo khoảng trắng |
| CJK (ZH, JA, KO) | 14–18 | 8–10 | **Không** ngắt theo khoảng trắng — cần luật riêng |
| RTL (AR, HE) | 37–42 | 17–20 | Cần shaping đúng (HarfBuzz) |
| Ấn Độ (HI, TA, TH) | 35–40 | 15–18 | Cần font có đủ glyph + shaping |

---

## 6. Các module chức năng

### 6.1 Source / Import Manager
Nhập video từ file hoặc nguồn được phép; chuẩn hoá tên file, metadata và checksum;
lưu source reference và thông tin quyền sử dụng do người dùng cung cấp.

### 6.2 Video Analyzer
Phân tích duration, resolution, FPS, aspect ratio, codec, audio tracks, language,
scene changes, face presence, **text-on-screen (có toạ độ vùng)**, subtitle/logo presence
và số lượng speaker ước tính.

> v3: kết quả `text-on-screen` phải ghi vào bảng `onscreen_text` kèm bounding box,
> không chỉ là cờ boolean.

### 6.3 Audio Separation & Processing
Demucs tách `vocals` / `background`; noise reduction; normalization; EQ/compression;
ducking BGM khi có speech.

> v3: bắt buộc **giữ lại track `background`** để tái dựng ở §9.

### 6.4 Speech-to-Text
Whisper hoặc provider tương đương; xuất transcript có **sentence-level và word-level timestamps**.
Word-level là bắt buộc, không phải tuỳ chọn — Duration Fitting và Subtitle đều phụ thuộc vào nó.

### 6.5 Speaker Diarization
Nhận diện nhiều người nói; gán speaker ID; map từng speaker sang voice profile.

### 6.6 Segment Planner — **MỚI**
Chủ sở hữu của toàn bộ việc gộp/tách giữa 4 tầng segment (§5).
Là module thuần logic, không gọi API — dễ test, nên có unit test đầy đủ từ đầu.

### 6.7 Translation & Localization
Dịch theo ngữ cảnh; giữ nguyên tên sản phẩm/thuật ngữ; hỗ trợ glossary, translation memory,
style guide, tone và locale.

> v3 bổ sung vào prompt:
> - **Budget độ dài**: số ký tự/âm tiết mục tiêu cho từng unit (xem §7).
> - **Bản địa hoá số liệu**: ngày tháng, đơn vị đo, tiền tệ, định dạng số — quy định trong
>   style guide, không để LLM tự quyết.
> - **Transcreation cho hook/CTA**: dịch sát nghĩa thường làm hỏng câu mở đầu và lời kêu gọi
>   hành động; đánh dấu các unit này để dịch thoáng.

### 6.8 Duration Fitting Engine — **MỚI** → xem §7

### 6.9 Voice / TTS Engine
TTS đa ngôn ngữ; voice profiles; speed, pitch, emotion; provider plug-in.

> v3: mỗi `tts_chunk` xuất thành **một file riêng có địa chỉ** (không render thẳng thành 1 track dài).
> Đây là điều kiện bắt buộc để partial re-run ở §11 hoạt động.
> Voice cloning chỉ dùng cho giọng đã được phép — có chứng từ trong `voice_consents`.

### 6.10 Forced Alignment — **MỚI** → xem §8

### 6.11 Subtitle & Caption Engine
Sinh SRT/VTT/ASS; chia dòng; highlight từ khoá; preset phong cách; safe area; animation;
kiểm soát độ dài và overlap.

> v3: **luôn dựng từ timestamp sau forced alignment** (nguyên tắc §2.9).

### 6.12 On-screen Text Localization — **MỚI**
- **MVP:** OCR các vùng đã phát hiện → gắn cờ → **chặn QC** → đẩy sang manual review.
  Không cố tự động che/vẽ lại ở giai đoạn này.
- **Sau MVP:** inpainting nền + overlay text đã dịch, chỉ áp cho vùng nền tĩnh.

Lý do đưa vào sớm: với video reup, title card và caption cháy sẵn rất phổ biến.
Giữ nguyên tiếng Anh trong bản tiếng Indonesia thì phần localization hỏng một nửa.

### 6.13 Lip-sync Engine
Đồng bộ khẩu hình khi video có khuôn mặt phù hợp; chế độ Auto/Fast/High Quality/Disabled;
xử lý nhiều khuôn mặt.

> **Cảnh báo phạm vi (§13):** module này kéo theo GPU, license và phần lớn độ phức tạp còn lại.
> Cần chốt sớm có đưa vào MVP hay không.

### 6.14 Branding & Composition
Logo, watermark, font, màu thương hiệu, intro/outro, CTA, crop/reframe, background,
template theo brand profile.

### 6.15 Render Engine
FFmpeg là lớp composition/render chính; preset 9:16, 1:1, 16:9; codec, bitrate, FPS, output profile.

> v3: dựng filter graph bằng **builder có cấu trúc**, không nối chuỗi string.
> Filter graph nối tay là nguồn bug khó debug nhất của loại tool này.

### 6.16 Quality Control → xem §15

### 6.17 Publishing & Analytics → xem §18.3

### 6.18 Job Queue / Retry / Cache / Cost → xem §16, §17

---

## 7. Duration Fitting Engine

> **Đây là bài toán khó nhất của toàn bộ lĩnh vực dubbing và là lỗ hổng lớn nhất của v2.**

### 7.1 Vấn đề

Cùng một câu, thời lượng đọc giữa các ngôn ngữ lệch nhau thường **15–35%**:
Anh → Tây Ban Nha / Pháp / Đức dài ra rõ rệt; Anh → Trung / Nhật co lại.

Ví dụ cụ thể: đoạn tiếng Anh dài 6,0 giây, dịch sang tiếng Tây Ban Nha, TTS đọc ra **7,4 giây**.
Không có bước ép khớp thì:

```
Segment 1: lệch +1,4s  -> còn chấp nhận được
Segment 2: lệch +1,1s  -> tổng +2,5s, bắt đầu thấy sai
Segment 8: tổng +9,2s  -> audio nói về cảnh đã trôi qua từ lâu
```

Hệ quả dây chuyền: audio trôi khỏi hình → lip-sync mất căn cứ → subtitle lệch →
QC báo fail hàng loạt mà không rõ nguyên nhân gốc.

### 7.2 Bốn chiến lược, áp theo thứ tự ưu tiên

Rẻ và ít hại nhất trước. Chỉ leo lên bước sau khi bước trước không đủ.

| # | Chiến lược | Cách làm | Ngưỡng an toàn |
|---|-----------|----------|----------------|
| 1 | **Dịch có ràng buộc** | Truyền budget ký tự/âm tiết vào prompt LLM, yêu cầu diễn đạt lại cho vừa | Luôn thử trước — rẻ nhất, chất lượng cao nhất |
| 2 | **Ăn vào khoảng lặng** | Mượn silence giữa các câu | Giữ lại tối thiểu 150–200 ms mỗi khoảng |
| 3 | **Chỉnh tempo TTS** | `atempo` trên audio đã sinh | **0,92 – 1,08**. Vượt ngưỡng tai người nghe ra ngay |
| 4 | **Co giãn hình** | Freeze frame / speed ramp ở đoạn không có mặt người | Phương án cuối; không dùng khi có face hoặc lip-sync |

Nếu cả 4 chiến lược không đủ → đánh dấu segment `needs_manual_review`, **không** ép bừa.

### 7.3 Vòng lặp thực thi

```
for unit in translation_units:
    target = unit.source_duration
    budget = estimate_char_budget(target, locale)   # theo tốc độ đọc của locale

    # Bước 1 — dịch có ràng buộc (tối đa 2 lần thử)
    text = translate(unit, char_budget=budget)
    audio = tts(text)
    if within(audio.duration, target, tol=0.10): -> DONE

    # Bước 2 — mượn khoảng lặng lân cận
    if silence_available(unit) >= deficit: -> DONE

    # Bước 3 — chỉnh tempo trong ngưỡng an toàn
    ratio = audio.duration / target
    if 0.92 <= ratio <= 1.08:
        audio = atempo(audio, ratio); -> DONE

    # Bước 4 — co giãn hình (chỉ khi không có face)
    if not unit.has_face: adjust_video_timing(); -> DONE

    -> flag needs_manual_review
```

### 7.4 Dữ liệu cần lưu

Bảng `segment_timing`: `target_duration`, `actual_duration`, `fit_strategy`,
`tempo_ratio`, `drift_ms`, `cumulative_drift_ms`.

`cumulative_drift_ms` là chỉ số QC bắt buộc — xem §15.

---

## 8. Forced Alignment & Subtitle

### 8.1 Vấn đề ở v2

v2 sinh subtitle từ timestamp của transcript **nguồn**. Nhưng người xem nghe audio **mới**
do TTS đọc, với nhịp hoàn toàn khác. Subtitle sẽ lệch một cách có hệ thống.

Đây là loại lỗi QC tự động **khó bắt nhất**: mọi file đều hợp lệ về kỹ thuật —
đúng định dạng, không overlap, không overflow — nhưng chữ hiện không khớp lời nói.

### 8.2 Giải pháp

Sau khi `timeline_assembly` xong, chạy forced alignment **trên chính audio sẽ phát**
để lấy lại word-level timestamp, rồi mới dựng subtitle cue.

- **Công cụ:** WhisperX hoặc Montreal Forced Aligner (MFA).
- **Đầu vào:** audio đã ghép + text đã dịch (đã biết nội dung → bài toán alignment, không phải STT).
- **Đầu ra:** word-timestamp chính xác trên timeline mới.

### 8.3 Nguyên tắc bất biến

> **Subtitle luôn sinh từ timestamp của audio sẽ phát, không bao giờ từ audio nguồn.**

Nguyên tắc này cũng áp dụng cho highlight từ khoá, karaoke-style caption và mọi hiệu ứng
phụ thuộc thời gian.

---

## 9. Audio Reconstruction

> Bổ sung tường minh ở v3 vì đây là lỗi dễ mắc và hậu quả rõ ngay.

Sau Demucs, audio nguồn tách thành hai phần. Track cuối phải được **tái dựng**, không phải thay thế:

```
audio_final =  mix( TTS_assembled,  background_gốc )
                     ^                 ^
                     giọng mới         nhạc nền + tiếng động của video gốc
```

Nếu chỉ thay nguyên track audio bằng TTS → **mất sạch nhạc nền, tiếng động, không khí video gốc**.
Output nghe như bản đọc chay và chất lượng cảm nhận tụt hẳn.

### Chuẩn hoá loudness

- Target: **≈ −14 LUFS** (các nền tảng lớn tự normalize về khoảng này — cần xác minh lại
  con số hiện hành trước khi chốt preset).
- Dùng `loudnorm` **hai lượt** (đo trước, áp sau). Một lượt cho kết quả không ổn định giữa các file.
- Không đặt target rõ ràng thì mỗi bản ngôn ngữ sẽ to nhỏ khác nhau.

### Ducking

Giảm background khi có speech, khôi phục khi im lặng — dùng sidechain compression,
tham số nằm trong render preset.

---

## 10. Data Model

### 10.1 Bảng giữ nguyên từ v2

| Bảng | Mục đích |
|------|----------|
| `projects` | Thông tin project, brand và cấu hình mặc định |
| `source_videos` | Source file, metadata, checksum, rights note |
| `transcripts` | Transcript và timestamps |
| `speakers` | Speaker profiles và mapping |
| `translations` | Bản dịch theo locale + **version** + **approved_by** |
| `voices` | Voice profiles/provider settings |
| `subtitle_presets` | Style và layout subtitle |
| `brand_profiles` | Logo, font, màu, intro/outro, CTA |
| `render_jobs` | Job, stage, progress, retry, error |
| `output_files` | Preview/final/intermediate metadata |
| `publishing_jobs` | Platform, account, schedule, status |
| `api_usage` | Token/character/GPU usage và cost |
| `error_logs` | Lỗi, stack/message, retry history |

### 10.2 Thay `segments` bằng 4 bảng

| Bảng | Mục đích |
|------|----------|
| `stt_segments` | Đoạn thô từ STT, cắt theo khoảng lặng |
| `translation_units` | Đơn vị dịch trọn nghĩa, có `char_budget` |
| `tts_chunks` | Chunk TTS, mỗi chunk trỏ tới **1 file audio riêng** |
| `subtitle_cues` | Cue hiển thị, kèm CPS và số dòng |
| `segment_links` | Mapping N:M giữa 4 tầng trên |

### 10.3 Bảng mới

| Bảng | Mục đích | Vì sao cần |
|------|----------|-----------|
| `segment_timing` | target/actual duration, `fit_strategy`, `drift_ms`, `cumulative_drift_ms` | Cốt lõi của Duration Fitting; là dữ liệu để QC bắt lỗi trôi tiếng |
| `approval_gates` | Ai duyệt stage nào, lúc nào, phiên bản nào | Biến "manual review" thành quy trình có vết |
| `voice_consents` | Chứng từ cho phép dùng giọng, phạm vi, thời hạn, file đính kèm | Chuyển ràng buộc pháp lý từ tài liệu thành dữ liệu kiểm tra được |
| `onscreen_text` | Vùng OCR (bbox), nội dung gốc, bản dịch, trạng thái xử lý | Nối Analyzer với QC thay vì để kết quả phân tích trôi đi |
| `stage_runs` | Mỗi lần chạy một stage: input hash, output ref, thời gian, chi phí | Nền tảng của cache, partial re-run và lineage |

### 10.4 Lineage

- `translations` có `version` và `approved_by`.
- `output_files` trỏ về **đúng version** của từng input đã tạo ra nó — không chỉ ghi `job_id`.

Chỉ khi đó nguyên tắc lineage ở §2.5 mới thực sự truy vết được:
*"video này dùng bản dịch nào, giọng nào, preset nào, ai duyệt."*

---

## 11. Stage Contract & Partial Re-run

### 11.1 Contract

Mỗi stage là một hàm thuần:

```
run(job_id, stage_input) -> stage_output
```

- Ghi kết quả xuống DB và storage **ngay từ dòng code đầu tiên** của dự án.
- Không gọi trực tiếp stage khác — điều phối là việc của orchestrator.
- Idempotent: chạy lại cùng input không tạo output trùng.

Nhờ contract này, việc gắn Celery/RQ ở Phase 3 chỉ là **đổi cách gọi**, không phải viết lại.
Đây là điểm sửa quan trọng nhất so với roadmap v2.

### 11.2 Approval Gates

Bốn cổng duyệt, cấu hình bật/tắt theo project:

```
transcript -> translation -> audio -> final
```

Mỗi cổng ghi vào `approval_gates`. Project chạy tự động hoàn toàn thì tắt hết;
project chất lượng cao thì bật cổng `translation` và `final`.

### 11.3 Partial Re-run

Tình huống thực tế thường gặp nhất: **người vận hành sửa một câu dịch sai thuật ngữ.**

Câu hỏi kiến trúc: sửa 1 unit thì chạy lại những gì?

```
Sửa translation_unit #12
   -> đánh dirty: unit #12
   -> TTS lại CHỈ chunk của unit #12
   -> forced align lại (rẻ, chạy trên audio ghép)
   -> timeline assembly lại (chỉ là ghép file)
   -> subtitle dựng lại
   -> REMUX  (không encode lại video)
```

Điều kiện bắt buộc để làm được:
1. Mỗi `tts_chunk` là **một file riêng có địa chỉ** (§6.9).
2. Composition là bước **ghép các file**, không phải một lệnh FFmpeg khổng lồ chạy một lần.
3. Có dependency graph giữa các stage + dirty-flag theo segment.

Thiết kế điều này **ngay từ đầu**. Sửa sau rất đắt.

---

## 12. Cấu trúc thư mục

```
/app
  /api
  /workers
    /import
    /analyzer
    /audio            # separation + processing + reconstruction
    /stt
    /diarization
    /segment_planner  # MỚI
    /translation
    /duration_fit     # MỚI
    /tts
    /forced_align     # MỚI
    /timeline         # MỚI
    /subtitle
    /onscreen_text    # MỚI
    /lipsync
    /render
    /qc
    /publishing
  /models
  /services
  /db
  /config
  /tests
    /fixtures         # clip mẫu 10s cho vòng lặp phát triển nhanh
/storage
  /projects/{project_id}/
    /source
    /analysis
    /audio
      /separated      # vocals + background
      /tts            # 1 file / chunk  <- điều kiện của partial re-run
      /assembled
    /transcript
    /translation
    /subtitle
    /preview
    /final
```

---

## 13. Technology Stack

| Layer | Công nghệ | Vai trò |
|-------|-----------|---------|
| Frontend | React / Next.js | Dashboard, preview, settings, batch jobs |
| Backend API | FastAPI (Python) | REST API, auth, job creation, project config |
| Database | PostgreSQL | Production DB; SQLite chỉ cho MVP nhỏ |
| Queue | Redis + Celery/RQ | Async jobs, retries, concurrency |
| Media | FFmpeg | Decode, encode, composition, audio mixing |
| STT | Whisper (pluggable) | Transcript + **word timestamps** |
| Alignment | WhisperX / MFA | Forced alignment trên audio mới |
| Separation | Demucs | Vocals / background separation |
| Translation | LLM provider (pluggable) | Localization theo context + budget độ dài |
| TTS | Provider abstraction | ElevenLabs / Edge-TTS / khác tuỳ use case |
| Lip-sync | Pluggable model | **Xem cảnh báo bên dưới** |
| OCR | PaddleOCR / Tesseract | On-screen text detection |
| Storage | Local / S3-compatible | Media assets và outputs |
| Automation | Official API + OAuth | Publishing |
| Monitoring | Structured logs + metrics | Error, performance, cost |

### 13.1 Soi chiếu với môi trường thật (macOS)

> Bốn điểm cần chốt **trước khi viết code**, không phải phát hiện ở tuần 4.

| Vấn đề | Thực trạng | Hướng xử lý |
|--------|-----------|-------------|
| **Lip-sync trên Mac** | Wav2Lip, SadTalker thiết kế cho CUDA — gần như không chạy được trên Apple Silicon | Thuê GPU ngoài (RunPod/Vast), hoặc **bỏ lip-sync khỏi MVP** |
| **License model** | Wav2Lip là license nghiên cứu **phi thương mại** | Rà license từng model trước khi đưa vào stack. Nếu output dùng để kiếm tiền, đây là rủi ro pháp lý thật |
| **Whisper** | `faster-whisper` (CTranslate2) chỉ chạy CPU trên Mac | Dùng bản có Metal: `whisper.cpp` hoặc MLX Whisper |
| **Encode** | libx264 chậm hơn nhiều lần | Bật `h264_videotoolbox` trên macOS; NVENC nếu chạy Linux + GPU |

### 13.2 Chi tiết media dễ bỏ sót

Những điểm dưới đây tốn nhiều ngày debug nếu phát hiện muộn:

- **Font fallback cho hardsub** — thiếu glyph là ra ô vuông. Hiếm ai test trước với
  tiếng Ả Rập, Hindi hay Thái. **Nhúng bộ Noto và khai báo fallback chain.**
- **RTL và CJK** — Ả Rập/Do Thái cần shaping đúng (libass + HarfBuzz);
  CJK có luật ngắt dòng riêng, không cắt theo khoảng trắng được.
- **Pixel format & GOP** — đặt `yuv420p` rõ ràng, kiểm soát keyframe interval;
  bỏ qua thì một số nền tảng từ chối file hoặc hiển thị sai màu.
- **Filter graph** — dựng bằng builder có cấu trúc, không nối chuỗi string (§6.15).

---

## 14. Preset System

| Preset | Nội dung |
|--------|----------|
| Locale preset | Language + locale + tone + glossary + style guide + **CPS/ký tự-dòng** + **tốc độ đọc** |
| Voice preset | Provider + voice + speed + pitch + emotion |
| Subtitle preset | Font + size + position + animation + keyword highlight + **font fallback chain** |
| Brand preset | Logo + colors + font + intro/outro + CTA |
| Render preset | Aspect ratio + resolution + FPS + codec + bitrate + **loudness target** + **pixel format** |
| Publishing preset | Platform + title template + description + hashtags + schedule + **ai_disclosure** |
| **Fitting preset** | Ngưỡng tempo, silence tối thiểu, tolerance drift, có cho phép co giãn hình hay không |

---

## 15. Quality Control Checklist

### Giữ từ v2
- **Video:** resolution/FPS/duration/codec/aspect ratio hợp lệ; không frame lỗi, frame đen, freeze bất thường.
- **Audio:** có audio, không clipping, loudness hợp lý, voice không bị BGM lấn, không silence bất thường.
- **Subtitle:** không overflow, không overlap, timing hợp lý, đủ nội dung, trong safe area.
- **Translation:** không thiếu segment, glossary đúng, không còn placeholder.
- **Lip-sync:** duration khớp, face region hợp lệ, không lỗi render.
- **Output:** file mở được, đúng preset, checksum lưu thành công.
- **Publishing:** chỉ publish khi QC = PASS và account authorization còn hợp lệ.

### Bổ sung ở v3 (quan trọng nhất)
- **Drift tích luỹ:** `cumulative_drift_ms` cuối video **< 300 ms**. Đây là chỉ số QC quan trọng nhất
  của toàn hệ thống — nó bắt được lỗi mà mọi kiểm tra khác bỏ sót.
- **Nguồn timestamp subtitle:** phải sinh từ forced alignment trên audio mới. Kiểm tra bằng cờ dữ liệu,
  không kiểm tra bằng mắt.
- **Background còn nguyên:** so sánh năng lượng dải tần nhạc nền giữa source và output —
  bắt trường hợp thay nhầm nguyên track.
- **Tempo ratio:** không segment nào vượt ngưỡng 0,92–1,08.
- **On-screen text:** nếu `onscreen_text` còn bản ghi `pending` → **QC FAIL**, đẩy manual review.
- **CPS theo locale:** không cue nào vượt CPS của ngôn ngữ đích.
- **Font coverage:** mọi ký tự trong subtitle có glyph trong font chain đã khai báo.

---

## 16. Job Queue, Retry và Cache

| Thành phần | Thiết kế |
|-----------|----------|
| Job ID | Định danh duy nhất cho mỗi `video × locale × pipeline` |
| Stage | 17 stage ở §4 |
| Status | `pending` / `running` / `succeeded` / `failed` / `cancelled` / **`needs_review`** |
| Retry | Tối đa N lần theo stage; exponential backoff cho API lỗi tạm thời |
| Cache key | `source checksum + model/provider + provider version + config version` |
| Concurrency | Giới hạn riêng CPU / GPU / API để tránh quá tải |
| Idempotency | Chạy lại cùng job không tạo output trùng |
| **Dirty flag** | Theo segment, để partial re-run (§11.3) biết cần chạy lại gì |
| **Dependency graph** | Stage nào phụ thuộc stage nào, để lan truyền dirty đúng hướng |

> Lưu ý cache key: **phải gồm cả provider version.** Provider đổi model mà key không đổi
> thì cache trả về kết quả cũ của model khác — lỗi rất khó truy.

---

## 17. Cost Management

Không dùng con số chi phí cố định làm ngân sách sản phẩm vì giá API/model thay đổi.
Tool phải tự đo usage thực tế.

- Track theo `video × locale × provider × model`.
- Ghi token, character, audio seconds, GPU seconds, storage GB-hours.
- Tổng hợp cost/job và cost/project.
- Soft limit và hard limit để chặn batch phát sinh chi phí ngoài dự kiến.
- Cho phép chọn local model hoặc cloud provider theo preset.

### 17.1 Ước tính trước khi chạy — **MỚI**

v2 chỉ có soft/hard limit — tức là chặn **khi đang chạy**. Cần thêm bước dry-run:

```
Trước khi batch khởi động:
  - đếm ký tự cần dịch (× số locale)
  - đếm giây audio cần TTS
  - ước GPU-second cho lip-sync (nếu bật)
  - ước storage phát sinh
  -> hiện TỔNG TIỀN DỰ KIẾN + yêu cầu người dùng xác nhận
```

Không có bước này thì lệnh batch 200 video chỉ được phát hiện là sai lầm sau khi đã tiêu tiền.

### 17.2 Dọn file trung gian

Mỗi video sinh ra hàng loạt WAV, PNG, file tạm. Không có lifecycle policy thì ổ đầy trong vài tuần.
Đặt retention theo loại artifact ngay từ đầu:

| Loại | Retention đề xuất |
|------|-------------------|
| `source` | Giữ đến khi project bị xoá |
| `separated`, `tts`, `assembled` | 30 ngày sau khi job hoàn tất |
| `preview` | 7 ngày |
| `final` | Giữ đến khi project bị xoá |
| `analysis`, `transcript`, `translation` | Giữ (nhẹ, và là dữ liệu cache đắt tiền) |

---

## 18. Security, Reliability & Compliance

### 18.1 Security (giữ từ v2)
- API key lưu trong secret store/environment, không plaintext trong database.
- OAuth token mã hoá, có cơ chế revoke/refresh.
- Phân quyền project/account nếu sau này multi-user.
- Log không chứa secret/API key.
- Giới hạn file size, duration và loại file đầu vào.
- Sandbox các tác vụ xử lý media không đáng tin cậy.
- Backup database và metadata; media storage có lifecycle policy.
- Mọi output liên kết về source/job để audit.

### 18.2 Compliance — **MỚI**

| Yêu cầu | Cách hiện thực |
|---------|---------------|
| **Công bố nội dung AI** | YouTube và TikTok đều yêu cầu khai báo nội dung tổng hợp; EU AI Act có nghĩa vụ minh bạch tương ứng. Thêm cờ `ai_disclosure` ở cấp output, tự set khi publish |
| **Đồng thuận giọng nói** | Bảng `voice_consents`: ngày, phạm vi sử dụng, thời hạn, file chứng từ. TTS chặn nếu voice profile không có consent hợp lệ |
| **Quyền sử dụng nguồn** | `source_videos.rights_note` là trường **bắt buộc**, không cho để trống |

> Nguyên tắc: chuyển ràng buộc pháp lý từ *câu chữ trong tài liệu* thành *dữ liệu kiểm tra được*.

### 18.3 Publishing — ràng buộc quota

> **Đây là ràng buộc định hình cả sản phẩm, cần biết trước khi thiết kế Phase 5.**

| Nền tảng | Ràng buộc (cần xác minh lại trước khi chốt) |
|----------|---------------------------------------------|
| YouTube | `videos.insert` ≈ 1.600 unit / hạn mức mặc định 10.000 unit/ngày → **≈ 6 video/ngày/project** |
| TikTok | Content Posting API yêu cầu qua **audit** mới được đăng trực tiếp; chưa audit chỉ đẩy được vào draft |
| Instagram | Graph API có giới hạn số bài trong 24 giờ; cần Business/Creator account |

**Hệ quả:** một tool sinh 40 video/ngày mà chỉ đăng được 6 thì nút thắt nằm ở publishing,
không nằm ở render. Cần:

1. Xác minh hạn mức hiện hành và **xin nâng quota sớm** (thủ tục mất thời gian).
2. Thiết kế publishing queue có rate-limit awareness và tự giãn lịch.
3. **Cân nhắc hướng đi khác:** YouTube hỗ trợ **nhiều audio track trên cùng một video**.
   Nếu thao tác được qua API thì đây là mô hình hoàn toàn khác so với xuất N video riêng —
   đáng đánh giá trước khi xây Phase 5.

---

## 19. Dashboard / UI

- **Dashboard:** tổng số video, jobs đang chạy, completed/failed, storage, API cost.
- **Projects:** source, target languages, brand profile, default voice, subtitle preset.
- **Video Workspace:** preview, transcript, translation, voice, subtitle, branding.
  - **Mới:** sửa inline từng `translation_unit` → hiện rõ "sẽ chạy lại gì" trước khi xác nhận.
  - **Mới:** hiển thị `drift_ms` theo từng segment dưới dạng thanh timeline — nhìn ra ngay chỗ trôi.
- **Batch Queue:** tiến độ từng `video × ngôn ngữ`, retry failed, priority.
- **QC Review:** cảnh báo subtitle overflow, audio mismatch, black/frozen frames, lip-sync lỗi,
  **drift vượt ngưỡng**, **on-screen text chưa xử lý**.
- **Publishing Calendar:** lịch đăng, trạng thái account, publish history, **quota còn lại hôm nay**.
- **Settings:** provider API keys, concurrency, storage policy, retention, output presets.

---

## 20. Roadmap

> **Sửa quan trọng so với v2:** v2 để PostgreSQL/queue/worker ở Phase 3, nghĩa là Phase 3
> phải mổ lại mọi thứ Phase 1 vừa viết. v3 kéo data model và stage contract lên Phase 1.
> Không cần queue ngay từ đầu, nhưng **data model và contract thì có**.

| Phase | Phạm vi | Ước lượng |
|-------|---------|-----------|
| **Phase 0 — Nền tảng** | Data model đầy đủ, stage contract, storage layout, fixture clip 10s, harness chạy pipeline tuần tự | 1 tuần |
| **Phase 1 — Trục localization** | import → analyze → separate → stt → segment planner → translate → **duration fit** → tts → **forced align** → **timeline** → subtitle → render | 3–4 tuần |
| **Phase 2 — Chất lượng** | Audio reconstruction, loudnorm, diarization, voice profiles, subtitle presets, font fallback, branding | 2 tuần |
| **Phase 3 — Hạ tầng** | Redis queue, worker tách tiến trình, retry, cache, partial re-run, approval gates, QC tự động | 2 tuần |
| **Phase 4 — Dashboard** | Next.js + FastAPI UI, project settings, video workspace, batch queue, QC review | 2 tuần |
| **Phase 5 — Publishing** | OAuth, official APIs, quota manager, schedule, publish history | 1–2 tuần |
| **Phase 6 — Mở rộng** | Lip-sync (nếu chốt làm), on-screen text inpainting, GPU tuning, monitoring, regression tests | 2–3 tuần |

**Ghi chú ước lượng:** con số trên thực tế nếu người làm đã từng dựng FFmpeg filter graph phức tạp.
Nếu chưa, hãy **cộng thêm 50% và cắt bớt số ngôn ngữ, đừng cắt phần hạ tầng**.

**Đổi thứ tự so với v2:** lip-sync chuyển từ Phase 2 xuống Phase 6 — xem §23.

---

## 21. Definition of Done cho MVP

### Giữ từ v2
- [ ] Nhập 1 video hợp lệ và tạo project thành công.
- [ ] Nhận dạng speech và timestamps ổn định.
- [ ] Dịch sang ít nhất 2 locale từ cùng một transcript nguồn.
- [ ] Tạo voice output và mix với BGM.
- [ ] Tạo subtitle hardsub theo preset.
- [ ] Render ít nhất một output 9:16.
- [ ] Có retry khi API tạm thời lỗi.
- [ ] Có cache để không chạy lại STT không cần thiết.
- [ ] Có QC pass/fail trước export.
- [ ] Có log đầy đủ cho mỗi stage.

### Bổ sung ở v3 — kiểm tra rằng kết quả *dùng được*
- [ ] **Drift cuối video < 300 ms** so với bản gốc, đo trên cả 2 locale.
- [ ] **Subtitle sinh từ forced alignment trên audio mới**, không phải timestamp nguồn.
- [ ] **Nhạc nền và tiếng động của bản gốc còn nguyên** trong output.
- [ ] **Sửa một câu dịch chỉ kích hoạt chạy lại đúng segment đó** và remux — không encode lại toàn bộ.
- [ ] **Có ước tính chi phí hiển thị trước khi batch chạy**, kèm bước xác nhận.
- [ ] **Một clip mẫu 10 giây chạy hết pipeline dưới 2 phút** — vòng lặp phát triển phải đủ nhanh để debug được.
- [ ] **Không segment nào vượt ngưỡng tempo 0,92–1,08** mà không được đánh dấu review.

---

## 22. Tính năng mở rộng sau MVP

- Content Variation Engine: hook/CTA/intro/outro và template theo campaign.
- On-screen text inpainting + overlay tự động.
- Thumbnail generator và metadata generator theo locale.
- Content calendar và campaign management.
- Performance analytics theo video/ngôn ngữ/brand profile.
- Multi-user/team workspace nếu phát triển thành SaaS.
- Provider failover: tự chuyển provider khi API/model lỗi hoặc quá tải.
- Model registry: thay model mà không đổi pipeline contract.
- YouTube multi-audio-track thay cho xuất N video riêng (§18.3).

---

## 23. Rủi ro và quyết định cần chốt

| # | Quyết định | Vì sao cần chốt sớm | Khuyến nghị |
|---|-----------|---------------------|-------------|
| 1 | **Lip-sync có vào MVP không?** | Kéo theo GPU, license phi thương mại và phần lớn độ phức tạp còn lại | **Không.** Phần lớn video reup dạng voice-over không có mặt người nói chính diện nên cũng không dùng tới. Đưa xuống Phase 6 |
| 2 | **Chạy local hay thuê GPU?** | Quyết định cả stack lẫn cấu trúc chi phí | Local trên Mac cho Phase 0–2 (whisper.cpp + videotoolbox); thuê GPU chỉ khi bật lip-sync |
| 3 | **Provider TTS nào?** | Quyết định chất lượng cảm nhận và chi phí đơn vị | Abstraction từ đầu; benchmark 2–3 provider trên cùng 1 clip mẫu trước khi khoá |
| 4 | **Bao nhiêu locale cho MVP?** | Mỗi locale thêm chi phí test theo cấp số | **2 locale** với hệ chữ khác nhau (VD: Tây Ban Nha + Nhật) để lộ sớm bug CPS/font/ngắt dòng |
| 5 | **N video riêng hay multi-audio-track?** | Đổi hoàn toàn thiết kế Phase 5 | Đánh giá khả năng API của YouTube trước khi xây publishing |

---

## Tóm lại

Kiến trúc v2 **không cần sửa** — cần bù phần nghiệp vụ nằm giữa các module.

Ba việc đáng làm trước khi viết dòng code đầu tiên:

1. **Tách khái niệm segment thành 4 tầng** (§5) — rẻ bây giờ, rất đắt sau này.
2. **Đặt Duration Fitting và Forced Alignment vào pipeline như stage chính thức** (§7, §8) —
   đây là hai mắt xích thiếu khiến output của v2 không dùng được dù mọi module đều chạy đúng.
3. **Kéo data model và stage contract lên Phase 0** (§11, §20) — để Phase 3 không phải viết lại Phase 1.

Và một quyết định nên chốt ngay vì nó đổi cả phạm vi: **lip-sync có thực sự cần cho MVP không** (§23).


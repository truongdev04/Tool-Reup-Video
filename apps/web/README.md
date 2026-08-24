# Web (Next.js) — dashboard Phase 4 (docs §19, §20)

Dashboard THẬT cho vận hành pipeline — khác dev viewer
(`apps/api/api/routes/pipeline.py` + `apps/api/api/static/`, chỉ để debug
pipeline cục bộ trên trang tĩnh). Gọi backend FastAPI (`apps/api`) qua CORS
(`apps/api/api/main.py`), không SSR — mọi trang là Client Component fetch dữ
liệu trực tiếp từ trình duyệt (`src/lib/api.ts`).

Lượt đầu (§19 "vòng vận hành lõi"): **Projects**, **Video Workspace** (xem +
sửa inline translation, drift timeline, QC, approval gate), **Batch Queue**.
**Publishing Calendar** và **Settings** để lượt sau — xem
`.claude/rules/tech-debt.md`.

## Chạy

```bash
# 1. Backend (từ gốc repo)
.venv/bin/uvicorn api.main:app --app-dir apps/api --port 8000

# 2. Frontend
cd apps/web
npm install    # lần đầu
npm run dev    # http://localhost:3000
```

Nếu cổng 8000 đã bị chiếm trên máy dev, đổi `--port` ở lệnh trên rồi copy
`.env.local.example` → `.env.local`, sửa `NEXT_PUBLIC_API_URL` cho khớp.

## Cấu trúc

- `src/lib/api.ts` — client + kiểu dữ liệu, khớp
  `apps/api/api/routes/dashboard.py`. Sửa route bên backend thì sửa cả hai
  chỗ — chưa có codegen kiểu OpenAPI → TS.
- `src/app/page.tsx` — Projects (danh sách).
- `src/app/projects/[id]/page.tsx` — chi tiết project + bảng job (batch queue
  thu hẹp trong 1 project).
- `src/app/queue/page.tsx` — Batch Queue toàn cục (mọi job, mọi project, lọc
  theo trạng thái).
- `src/app/jobs/[id]/page.tsx` — Video Workspace: transcript/bản dịch (sửa
  inline qua `UnitEditor`), drift timeline (`DriftTimeline`), QC, approval
  gate (`GatesPanel`).

## Sửa inline một câu dịch — luồng thật

`UnitEditor` gọi 2 API liên tiếp: `PATCH /api/dashboard/units/{id}` (ghi bản
dịch mới, KHÔNG gọi lại LLM — xem `services/translation_edit.py`) rồi
`POST /api/dashboard/jobs/{id}/rerun-downstream` (chạy lại đúng tập stage phụ
thuộc TRANSLATE, không chạy lại TRANSLATE). Danh sách "sẽ chạy lại gì" lấy từ
`GET /api/dashboard/rerun-preview` — tĩnh, không phụ thuộc unit nào, fetch một
lần lúc vào trang.

## Giới hạn đã biết

- Không có auth — ai mở được `localhost:3000` cũng sửa/duyệt được (dev tool
  nội bộ, chưa deploy). Chốt trước khi expose ra ngoài máy dev.
- `Nav`/routing chưa có Publishing Calendar, Settings — điều hướng vào 2 mục
  đó chưa tồn tại.
- Không có optimistic update / websocket — mọi thay đổi phải bấm lại hoặc
  chờ `onSaved`/`onChanged` refetch. Batch Queue không tự refresh khi job
  đang chạy nền (Celery) đổi trạng thái — phải tự bấm F5.

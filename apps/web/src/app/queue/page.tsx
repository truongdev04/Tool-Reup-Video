"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, type QueueJob } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

const STATUS_FILTERS = [
  "",
  "pending",
  "running",
  "succeeded",
  "needs_review",
  "failed",
  "cancelled",
];

export default function QueuePage() {
  const [jobs, setJobs] = useState<QueueJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    // Không reset jobs về null trước khi fetch (giữ bảng cũ hiện tới khi có
    // dữ liệu mới) — set state đồng bộ ngay trong thân effect bị
    // react-hooks/set-state-in-effect cảnh báo cascading render.
    api
      .listJobs(status ? { status } : undefined)
      .then(setJobs)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [status]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Batch Queue</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Mọi job (video × locale) của mọi project, mới nhất trước.
          </p>
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s || "Tất cả trạng thái"}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {!error && jobs === null && <p className="text-sm text-slate-500">Đang tải...</p>}

      {jobs && (
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2">Project</th>
                <th className="px-4 py-2">Locale</th>
                <th className="px-4 py-2">Trạng thái</th>
                <th className="px-4 py-2">Stage</th>
                <th className="px-4 py-2">Tiến độ</th>
                <th className="px-4 py-2">Retry</th>
                <th className="px-4 py-2">Lỗi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {jobs.map((j) => (
                <tr key={j.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td className="px-4 py-3">
                    <Link href={`/projects/${j.project_id}`} className="hover:underline">
                      {j.project_name ?? j.project_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <Link href={`/jobs/${j.id}`} className="font-medium hover:underline">
                      {j.locale}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {j.current_stage ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                      <div
                        className="h-full bg-slate-600 dark:bg-slate-300"
                        style={{ width: `${Math.round(j.progress * 100)}%` }}
                      />
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {j.retry_count > 0 ? j.retry_count : "—"}
                  </td>
                  <td className="max-w-xs truncate px-4 py-3 text-red-600 dark:text-red-400" title={j.error_message ?? ""}>
                    {j.error_message ?? ""}
                  </td>
                </tr>
              ))}
              {jobs.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                    Không có job nào khớp bộ lọc
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

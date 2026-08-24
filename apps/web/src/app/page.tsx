"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, type Project } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Projects</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Mỗi project = 1 video nguồn × nhiều locale đích.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          Không gọi được API dashboard: {error}. Kiểm tra backend đang chạy
          (<code>uvicorn api.main:app --app-dir apps/api --port 8000</code>).
        </div>
      )}

      {!error && projects === null && (
        <p className="text-sm text-slate-500">Đang tải...</p>
      )}

      {projects !== null && projects.length === 0 && (
        <p className="text-sm text-slate-500">
          Chưa có project nào. Chạy <code>scripts/run_pipeline.py</code> hoặc dev
          viewer để tạo project đầu tiên.
        </p>
      )}

      {projects && projects.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2">Project</th>
                <th className="px-4 py-2">Locale đích</th>
                <th className="px-4 py-2">Video</th>
                <th className="px-4 py-2">Jobs</th>
                <th className="px-4 py-2">Tạo lúc</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {projects.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td className="px-4 py-3">
                    <Link href={`/projects/${p.id}`} className="font-medium hover:underline">
                      {p.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {p.target_locales.join(", ") || "—"}
                  </td>
                  <td className="px-4 py-3">{p.source_video_count}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(p.jobs_by_status).map(([status, count]) => (
                        <span key={status} className="flex items-center gap-1">
                          <StatusBadge status={status} />
                          <span className="text-xs text-slate-500">×{count}</span>
                        </span>
                      ))}
                      {p.job_count === 0 && <span className="text-xs text-slate-400">chưa có</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {new Date(p.created_at).toLocaleString("vi-VN")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

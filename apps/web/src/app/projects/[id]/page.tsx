"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, type ProjectDetail } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .projectDetail(id)
      .then(setProject)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [id]);

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
        {error}
      </div>
    );
  }
  if (!project) return <p className="text-sm text-slate-500">Đang tải...</p>;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-slate-500 hover:underline">
          ← Projects
        </Link>
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Locale đích: {project.target_locales.join(", ") || "—"}
        </p>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
          Video nguồn ({project.source_videos.length})
        </h2>
        <ul className="space-y-1 text-sm">
          {project.source_videos.map((s) => (
            <li key={s.id} className="text-slate-700 dark:text-slate-300">
              {s.filename}{" "}
              <span className="text-slate-400">
                ({s.source_locale ?? "locale nguồn chưa rõ"})
              </span>
            </li>
          ))}
          {project.source_videos.length === 0 && (
            <li className="text-slate-400">Chưa có video nào</li>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
          Jobs ({project.jobs.length})
        </h2>
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2">Locale</th>
                <th className="px-4 py-2">Video</th>
                <th className="px-4 py-2">Trạng thái</th>
                <th className="px-4 py-2">Stage hiện tại</th>
                <th className="px-4 py-2">Tiến độ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {project.jobs.map((j) => (
                <tr key={j.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td className="px-4 py-3">
                    <Link href={`/jobs/${j.id}`} className="font-medium hover:underline">
                      {j.locale}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {j.source_filename ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {j.current_stage ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                      <div
                        className="h-full bg-slate-600 dark:bg-slate-300"
                        style={{ width: `${Math.round(j.progress * 100)}%` }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
              {project.jobs.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    Chưa có job nào cho project này
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

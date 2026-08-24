"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, apiBaseUrl, ApiError, type JobWorkspace } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import DriftTimeline from "@/components/DriftTimeline";
import UnitEditor from "@/components/UnitEditor";
import GatesPanel from "@/components/GatesPanel";

export default function JobWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rerunStages, setRerunStages] = useState<string[]>([]);

  const load = useCallback(() => {
    api
      .jobWorkspace(id)
      .then(setJob)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [id]);

  useEffect(() => {
    load();
    api.rerunPreview().then((r) => setRerunStages(r.stages));
  }, [load]);

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
        {error}
      </div>
    );
  }
  if (!job) return <p className="text-sm text-slate-500">Đang tải...</p>;

  return (
    <div className="space-y-8">
      <div>
        <Link href={`/projects/${job.project_id}`} className="text-sm text-slate-500 hover:underline">
          ← {job.project_name ?? "Project"}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">
            {job.source_filename} · {job.locale}
          </h1>
          <StatusBadge status={job.status} />
          {job.current_stage && (
            <span className="text-xs text-slate-400">stage: {job.current_stage}</span>
          )}
        </div>
        {job.error_message && (
          <p className="mt-2 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
            {job.error_message}
          </p>
        )}
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">Approval gates</h2>
        <GatesPanel jobId={job.id} gates={job.gates} jobStatus={job.status} onChanged={load} />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">
          Drift timeline (§7, §21 — ngưỡng 300ms)
        </h2>
        <DriftTimeline units={job.units} />
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">
            QC {job.qc_verdict && <StatusBadge status={job.qc_verdict} />}
          </h2>
        </div>
        {job.qc_findings.length === 0 && (
          <p className="text-sm text-slate-400">Chưa có finding nào (hoặc QC chưa chạy).</p>
        )}
        {job.qc_findings.length > 0 && (
          <ul className="space-y-1 text-sm">
            {job.qc_findings.map((f, i) => (
              <li key={i} className="flex items-start gap-2">
                <StatusBadge status={f.verdict} />
                <span>
                  <span className="font-medium">{f.check}</span>: {f.message}
                </span>
              </li>
            ))}
          </ul>
        )}
        {job.final_video_url && (
          <video
            controls
            src={`${apiBaseUrl()}${job.final_video_url}`}
            className="mt-2 max-w-md rounded-lg border border-slate-200 dark:border-slate-800"
          />
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">
          Transcript &amp; bản dịch ({job.units.length} đơn vị)
        </h2>
        <div className="space-y-3">
          {job.units.map((u) => (
            <div
              key={u.id}
              className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"
            >
              <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
                <span>
                  #{u.idx} · {(u.start_ms / 1000).toFixed(1)}s–{(u.end_ms / 1000).toFixed(1)}s
                  {u.needs_transcreation && <span className="ml-2 text-purple-500">transcreation</span>}
                </span>
                {u.drift && (
                  <span className={u.drift.needs_manual_review ? "text-red-500" : ""}>
                    drift {u.drift.drift_ms}ms · tích luỹ {u.drift.cumulative_drift_ms}ms ·{" "}
                    {u.drift.fit_strategy}
                    {u.drift.needs_manual_review && " · cần xem lại"}
                  </span>
                )}
              </div>
              <p className="mb-2 text-sm text-slate-500 dark:text-slate-400">{u.source_text}</p>
              <UnitEditor
                unit={u}
                jobId={job.id}
                locale={job.locale}
                rerunStages={rerunStages}
                onSaved={load}
              />
              {u.audio_url && (
                <audio controls src={`${apiBaseUrl()}${u.audio_url}`} className="mt-2 h-8 w-full" />
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

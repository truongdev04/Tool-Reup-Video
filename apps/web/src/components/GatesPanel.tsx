"use client";

import { useState } from "react";
import { api, ApiError, type Gate, type PipelineReport } from "@/lib/api";

const GATE_LABEL: Record<string, string> = {
  transcript: "Transcript",
  translation: "Translation",
  audio: "Audio",
  final: "Final",
};

interface Props {
  jobId: string;
  gates: Gate[];
  jobStatus: string;
  onChanged: () => void;
}

export default function GatesPanel({ jobId, gates, jobStatus, onChanged }: Props) {
  const [approvedBy, setApprovedBy] = useState("");
  const [busyGate, setBusyGate] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastReport, setLastReport] = useState<PipelineReport | null>(null);

  const pending = gates.filter((g) => g.is_enabled && !g.approved_at);
  const anyEnabled = gates.some((g) => g.is_enabled);

  if (!anyEnabled) {
    return (
      <p className="text-sm text-slate-400">
        Project này chưa bật approval gate nào — pipeline chạy tự động hoàn toàn (§11.2).
      </p>
    );
  }

  const approve = async (gate: string) => {
    if (!approvedBy.trim()) {
      setError("Cần điền tên/email người duyệt");
      return;
    }
    setError(null);
    setBusyGate(gate);
    try {
      await api.approveGate(jobId, gate, { approved_by: approvedBy.trim() });
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusyGate(null);
    }
  };

  const resume = async () => {
    setError(null);
    setResuming(true);
    try {
      const report = await api.resumeJob(jobId);
      setLastReport(report);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setResuming(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {gates.map((g) => (
          <div
            key={g.gate}
            className={`rounded-md border p-2 text-xs ${
              !g.is_enabled
                ? "border-slate-200 text-slate-400 dark:border-slate-800"
                : g.approved_at
                  ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30"
                  : "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30"
            }`}
          >
            <div className="font-medium">{GATE_LABEL[g.gate] ?? g.gate}</div>
            {!g.is_enabled && <div>tắt</div>}
            {g.is_enabled && g.approved_at && (
              <div>đã duyệt · {g.approved_by}</div>
            )}
            {g.is_enabled && !g.approved_at && (
              <div className="mt-1">
                <button
                  onClick={() => approve(g.gate)}
                  disabled={busyGate !== null}
                  className="rounded bg-amber-600 px-2 py-1 font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  {busyGate === g.gate ? "..." : "Duyệt"}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      <input
        value={approvedBy}
        onChange={(e) => setApprovedBy(e.target.value)}
        placeholder="Tên/email người duyệt (dùng cho mọi nút Duyệt ở trên)"
        className="w-full max-w-sm rounded border border-slate-300 bg-white px-2 py-1.5 text-xs dark:border-slate-600 dark:bg-slate-900"
      />

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}

      {jobStatus === "needs_review" && (
        <button
          onClick={resume}
          disabled={resuming || pending.length > 0}
          title={pending.length > 0 ? "Duyệt hết cổng đang chờ trước" : undefined}
          className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {resuming ? "Đang chạy tiếp..." : "Chạy tiếp pipeline"}
        </button>
      )}

      {lastReport && (
        <div className="text-xs text-slate-500">
          Kết quả: {lastReport.ok ? "OK" : "có lỗi"} · {lastReport.outcomes.length} stage,{" "}
          {lastReport.cached_count} dùng cache, {lastReport.total_ms}ms
        </div>
      )}
    </div>
  );
}

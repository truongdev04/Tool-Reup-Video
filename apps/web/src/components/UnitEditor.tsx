"use client";

import { useState } from "react";
import { api, ApiError, type WorkspaceUnit } from "@/lib/api";

const STAGE_LABEL: Record<string, string> = {
  duration_fit: "Duration Fit",
  tts: "TTS (đọc lại giọng)",
  forced_align: "Forced Align",
  timeline_assembly: "Timeline Assembly",
  subtitle: "Subtitle",
  onscreen_text: "Onscreen Text",
  lipsync: "Lipsync",
  compose: "Compose",
  render: "Render (encode video)",
  qc: "QC",
  publish: "Publish",
};

interface Props {
  unit: WorkspaceUnit;
  jobId: string;
  locale: string;
  rerunStages: string[];
  onSaved: () => void;
}

export default function UnitEditor({ unit, jobId, locale, rerunStages, onSaved }: Props) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(unit.translated_text ?? "");
  const [editedBy, setEditedBy] = useState("");
  const [busy, setBusy] = useState<"idle" | "saving" | "rerunning">("idle");
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  if (!editing) {
    return (
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-slate-800 dark:text-slate-200">
          {unit.translated_text ?? <span className="text-slate-400">(chưa dịch)</span>}
          {unit.translation_version && unit.translation_version > 1 && (
            <span className="ml-2 text-xs text-slate-400">v{unit.translation_version}</span>
          )}
        </p>
        <button
          onClick={() => setEditing(true)}
          className="shrink-0 text-xs text-slate-500 hover:text-slate-900 hover:underline dark:hover:text-slate-100"
        >
          Sửa
        </button>
      </div>
    );
  }

  const save = async () => {
    if (!editedBy.trim()) {
      setError("Cần điền tên/email người sửa (approved_by, §10.4 lineage)");
      return;
    }
    setError(null);
    setBusy("saving");
    try {
      await api.editUnit(unit.id, { locale, text, edited_by: editedBy.trim() });
      setBusy("rerunning");
      await api.rerunDownstream(jobId);
      setApplied(true);
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy("idle");
    }
  };

  return (
    <div className="space-y-2 rounded-md border border-slate-300 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800/50">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
      />
      <input
        value={editedBy}
        onChange={(e) => setEditedBy(e.target.value)}
        placeholder="Tên/email người sửa"
        className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
      />

      <div className="rounded bg-amber-50 px-2 py-1.5 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
        Lưu sẽ chạy lại: {rerunStages.map((s) => STAGE_LABEL[s] ?? s).join(" → ")}
      </div>

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}

      <div className="flex gap-2">
        <button
          onClick={save}
          disabled={busy !== "idle"}
          className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {busy === "saving" ? "Đang lưu..." : busy === "rerunning" ? "Đang chạy lại..." : "Lưu & áp dụng"}
        </button>
        <button
          onClick={() => {
            setEditing(false);
            setText(unit.translated_text ?? "");
            setError(null);
          }}
          disabled={busy !== "idle"}
          className="rounded border border-slate-300 px-3 py-1.5 text-xs dark:border-slate-600"
        >
          Huỷ
        </button>
      </div>
      {applied && <p className="text-xs text-emerald-600 dark:text-emerald-400">Đã áp dụng.</p>}
    </div>
  );
}

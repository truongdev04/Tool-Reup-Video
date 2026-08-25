"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, type PipelineReport, type PublishingAccount, type PublishingHistoryEntry } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function PublishPanel({ jobId, defaultTitle }: { jobId: string; defaultTitle: string }) {
  const [accounts, setAccounts] = useState<PublishingAccount[] | null>(null);
  const [history, setHistory] = useState<PublishingHistoryEntry[]>([]);
  const [accountId, setAccountId] = useState("");
  const [title, setTitle] = useState(defaultTitle);
  const [hashtags, setHashtags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<PipelineReport | null>(null);

  const load = () => {
    api.listAccounts().then((all) => setAccounts(all.filter((a) => a.usable)));
    api.jobPublishing(jobId).then((r) => setHistory(r.history));
  };

  useEffect(load, [jobId]);

  const submit = async () => {
    if (!accountId || !title.trim()) return;
    const account = accounts?.find((a) => a.id === accountId);
    if (!account) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.publishJob(jobId, {
        platform: account.platform, account_id: accountId, title: title.trim(),
        hashtags: hashtags.split(",").map((h) => h.trim()).filter(Boolean),
      });
      setReport(r);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (accounts !== null && accounts.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        Chưa có tài khoản publish nào khả dụng —{" "}
        <Link href="/publish" className="underline">
          kết nối ở Publishing Calendar
        </Link>
        .
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
        >
          <option value="">Chọn tài khoản...</option>
          {accounts?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label} ({a.platform})
            </option>
          ))}
        </select>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Tiêu đề"
          className="min-w-[200px] flex-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
        />
        <input
          value={hashtags}
          onChange={(e) => setHashtags(e.target.value)}
          placeholder="hashtag, cách nhau bởi dấu phẩy"
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
        />
        <button
          onClick={submit}
          disabled={busy || !accountId || !title.trim()}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {busy ? "Đang publish..." : "Publish"}
        </button>
      </div>

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      {report && (
        <p className="text-xs text-slate-500">
          {report.outcomes[0]?.note ?? (report.ok ? "Đã gửi." : "Có lỗi.")}
        </p>
      )}

      {history.length > 0 && (
        <ul className="space-y-1 text-xs text-slate-500 dark:text-slate-400">
          {history.map((h) => (
            <li key={h.id} className="flex items-center gap-2">
              <StatusBadge status={h.status} />
              <span>
                {h.platform} · {h.platform_video_id ?? "—"} ·{" "}
                {h.published_at ? new Date(h.published_at).toLocaleString("vi-VN") : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

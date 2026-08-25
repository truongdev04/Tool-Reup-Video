"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type PublishingAccount, type PublishingHistoryEntry, type PublishingPlatform, type QuotaEntry } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function PublishingCalendarPage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Đang tải...</p>}>
      <PublishingCalendarInner />
    </Suspense>
  );
}

function PublishingCalendarInner() {
  const searchParams = useSearchParams();
  const [platforms, setPlatforms] = useState<PublishingPlatform[] | null>(null);
  const [accounts, setAccounts] = useState<PublishingAccount[] | null>(null);
  const [quota, setQuota] = useState<QuotaEntry[] | null>(null);
  const [history, setHistory] = useState<PublishingHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPlatform, setSelectedPlatform] = useState("");
  const [label, setLabel] = useState("");

  const load = () => {
    api.listPlatforms().then(setPlatforms).catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
    api.listAccounts().then(setAccounts).catch(() => {});
    api.quotaSummary().then(setQuota).catch(() => {});
    api.publishingHistory().then(setHistory).catch(() => {});
  };

  useEffect(load, []);

  const connected = searchParams.get("connected");
  const denied = searchParams.get("denied");

  const connect = () => {
    if (!selectedPlatform || !label.trim()) return;
    window.location.href = api.authorizeUrl(selectedPlatform, label.trim());
  };

  const revoke = async (id: string) => {
    await api.revokeAccount(id);
    load();
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Publishing Calendar</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Tài khoản đã kết nối, quota còn lại hôm nay, lịch sử publish (§18.1, §18.3, §19).
        </p>
      </div>

      {connected && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
          Đã kết nối tài khoản thành công.
        </div>
      )}
      {denied && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          Đã từ chối cấp quyền — chưa kết nối tài khoản nào.
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">Kết nối tài khoản mới</h2>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedPlatform}
            onChange={(e) => setSelectedPlatform(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
          >
            <option value="">Chọn nền tảng...</option>
            {platforms?.map((p) => (
              <option key={p.id} value={p.id} disabled={!p.is_configured}>
                {p.name} {!p.is_configured ? "(thiếu OAuth app)" : ""}
              </option>
            ))}
          </select>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Tên gợi nhớ (vd. Kênh YouTube chính)"
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
          <button
            onClick={connect}
            disabled={!selectedPlatform || !label.trim()}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            Kết nối
          </button>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">
          Tài khoản đã kết nối &amp; quota còn lại hôm nay
        </h2>
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2">Tài khoản</th>
                <th className="px-4 py-2">Nền tảng</th>
                <th className="px-4 py-2">Trạng thái</th>
                <th className="px-4 py-2">Quota hôm nay</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {accounts?.map((a) => {
                const q = quota?.find((q) => q.account_id === a.id);
                return (
                  <tr key={a.id}>
                    <td className="px-4 py-3">{a.label}</td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{a.platform}</td>
                    <td className="px-4 py-3">
                      {a.is_revoked ? (
                        <StatusBadge status="cancelled" />
                      ) : a.usable ? (
                        <StatusBadge status="succeeded" />
                      ) : (
                        <StatusBadge status="failed" />
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                      {q ? `còn ${q.remaining_uploads} lượt (${q.used_units}/${q.limit_units} đơn vị)` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {!a.is_revoked && (
                        <button
                          onClick={() => revoke(a.id)}
                          className="text-xs text-red-600 hover:underline dark:text-red-400"
                        >
                          Thu hồi
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {accounts?.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    Chưa kết nối tài khoản nào
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">Lịch sử publish</h2>
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2">Lúc</th>
                <th className="px-4 py-2">Nền tảng</th>
                <th className="px-4 py-2">Trạng thái</th>
                <th className="px-4 py-2">Video ID</th>
                <th className="px-4 py-2">Đơn vị quota</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {history?.map((h) => (
                <tr key={h.id}>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {h.published_at ? new Date(h.published_at).toLocaleString("vi-VN") : "—"}
                  </td>
                  <td className="px-4 py-3">{h.platform}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={h.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {h.platform_video_id ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {h.quota_units_used ?? "—"}
                  </td>
                </tr>
              ))}
              {history?.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    Chưa publish lần nào
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

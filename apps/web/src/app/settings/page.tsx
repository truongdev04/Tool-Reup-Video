"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type ProviderStatus, type SettingsPlatformStatus, type SettingsStatus } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

function ConfiguredBadge({ ok }: { ok: boolean }) {
  return <StatusBadge status={ok ? "succeeded" : "failed"} />;
}

function ProviderTable({ title, rows }: { title: string; rows: ProviderStatus[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          <tr>
            <th className="px-4 py-2" colSpan={4}>{title}</th>
          </tr>
          <tr>
            <th className="px-4 py-2">Provider</th>
            <th className="px-4 py-2">Adapter</th>
            <th className="px-4 py-2">Biến môi trường</th>
            <th className="px-4 py-2">Trạng thái</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
          {rows.map((p) => (
            <tr key={p.id}>
              <td className="px-4 py-3 font-medium">{p.name}</td>
              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{p.adapter}</td>
              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                {p.api_key_env ?? "— (không cần key)"}
              </td>
              <td className="px-4 py-3">
                <ConfiguredBadge ok={p.is_configured} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState<SettingsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.settingsStatus().then(setData).catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
        {error}
      </div>
    );
  }
  if (!data) return <p className="text-sm text-slate-500">Đang tải...</p>;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Chỉ xem trạng thái — API key luôn đọc từ biến môi trường tại thời điểm
          gọi, không lưu DB nên không sửa được ở đây (§18.1). Đổi biến môi
          trường rồi khởi động lại backend để cập nhật.
        </p>
        <p className="mt-1 text-xs text-slate-400">config_version: {data.config_version}</p>
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">ffmpeg-full</h2>
        <div className="rounded-lg border border-slate-200 p-4 text-sm dark:border-slate-800">
          <div className="flex items-center gap-2">
            <ConfiguredBadge ok={data.ffmpeg.ok} />
            <span className="text-slate-500 dark:text-slate-400">{data.ffmpeg.ffmpeg_bin}</span>
          </div>
          {data.ffmpeg.missing.length > 0 && (
            <ul className="mt-2 list-inside list-disc text-red-600 dark:text-red-400">
              {data.ffmpeg.missing.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="space-y-2">
        <ProviderTable title="Provider dịch (translation)" rows={data.translation_providers} />
      </section>

      <section className="space-y-2">
        <ProviderTable title="Provider TTS" rows={data.tts_providers} />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">Nền tảng publish</h2>
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2">Nền tảng</th>
                <th className="px-4 py-2">Cần OAuth app</th>
                <th className="px-4 py-2">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {data.publishing_platforms.map((p: SettingsPlatformStatus) => (
                <tr key={p.id}>
                  <td className="px-4 py-3 font-medium">{p.name}</td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {p.needs_oauth_app ? "Có" : "Không"}
                  </td>
                  <td className="px-4 py-3">
                    <ConfiguredBadge ok={p.is_configured} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">Diarize (§6.5)</h2>
        <div className="rounded-lg border border-slate-200 p-4 text-sm dark:border-slate-800">
          <p>Model: {data.diarization.model}</p>
          <p className="text-slate-500 dark:text-slate-400">
            min_speakers: {data.diarization.min_speakers ?? "tự đoán"} · max_speakers:{" "}
            {data.diarization.max_speakers ?? "tự đoán"}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <span>HF_TOKEN:</span>
            <ConfiguredBadge ok={data.diarization.hf_token_configured} />
            {!data.diarization.hf_token_configured && (
              <span className="text-xs text-slate-400">
                thiếu — diarize tự bỏ qua, không chặn pipeline
              </span>
            )}
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">
          Retention (§17.2 — chỉ xem, chưa có tiến trình purge tự động)
        </h2>
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2">Artifact</th>
                <th className="px-4 py-2">Giữ lại</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {Object.entries(data.retention_days).map(([kind, days]) => (
                <tr key={kind}>
                  <td className="px-4 py-3">{kind}</td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {days === null ? "vĩnh viễn" : `${days} ngày`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">Ngưỡng duration fit / QC</h2>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <p className="text-xs text-slate-400">max_cumulative_drift_ms</p>
            <p className="font-medium">{data.thresholds.max_cumulative_drift_ms}ms</p>
          </div>
          <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <p className="text-xs text-slate-400">tempo range</p>
            <p className="font-medium">
              {data.thresholds.tempo_min}–{data.thresholds.tempo_max}
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <p className="text-xs text-slate-400">min_silence_keep_ms</p>
            <p className="font-medium">{data.thresholds.min_silence_keep_ms}ms</p>
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-600 dark:text-slate-300">Hạ tầng</h2>
        <div className="rounded-lg border border-slate-200 p-4 text-sm dark:border-slate-800">
          <p>database_url: {data.infra.database_url}</p>
          <p>storage_root: {data.infra.storage_root}</p>
          <p>redis_url: {data.infra.redis_url}</p>
          <div className="mt-1 flex items-center gap-2">
            <span>token_encryption_key:</span>
            <ConfiguredBadge ok={data.infra.token_encryption_key_configured} />
            {!data.infra.token_encryption_key_configured && (
              <span className="text-xs text-amber-600 dark:text-amber-400">
                chưa đặt — dùng khoá tạm sinh mỗi lần khởi động, KHÔNG dùng cho token thật
              </span>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

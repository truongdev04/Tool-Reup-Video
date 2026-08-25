"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type CostEstimate, type ProviderStatus } from "@/lib/api";

export default function CostEstimatePanel({
  projectId,
  targetLocales,
}: {
  projectId: string;
  targetLocales: string[];
}) {
  const [translationProviders, setTranslationProviders] = useState<ProviderStatus[] | null>(null);
  const [ttsProviders, setTtsProviders] = useState<ProviderStatus[] | null>(null);
  const [translationProvider, setTranslationProvider] = useState("mock");
  const [ttsProvider, setTtsProvider] = useState("macos_say");
  const [selectedLocales, setSelectedLocales] = useState<Set<string>>(new Set(targetLocales));
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.settingsStatus().then((s) => {
      setTranslationProviders(s.translation_providers);
      setTtsProviders(s.tts_providers);
    }).catch(() => {});
  }, []);

  const toggleLocale = (locale: string) => {
    setSelectedLocales((prev) => {
      const next = new Set(prev);
      if (next.has(locale)) next.delete(locale);
      else next.add(locale);
      return next;
    });
  };

  const run = async () => {
    if (selectedLocales.size === 0) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.estimateCost(projectId, {
        locales: [...selectedLocales],
        translation_provider: translationProvider,
        tts_provider: ttsProvider,
      });
      setEstimate(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-400">
        Ước tính KHÔNG gọi mạng, KHÔNG tốn tiền — chỉ đọc dữ liệu đã có + giá niêm yết/lịch sử
        usage thật để dự đoán tổng chi phí trước khi chạy thật (§17.1).
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs text-slate-400">Locale</label>
          <div className="mt-1 flex flex-wrap gap-2">
            {targetLocales.map((l) => (
              <label
                key={l}
                className="flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700"
              >
                <input
                  type="checkbox"
                  checked={selectedLocales.has(l)}
                  onChange={() => toggleLocale(l)}
                />
                {l}
              </label>
            ))}
            {targetLocales.length === 0 && (
              <span className="text-xs text-slate-400">project chưa khai target_locales</span>
            )}
          </div>
        </div>

        <div>
          <label className="block text-xs text-slate-400">Provider dịch</label>
          <select
            value={translationProvider}
            onChange={(e) => setTranslationProvider(e.target.value)}
            className="mt-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          >
            {(translationProviders ?? [{ id: translationProvider, name: translationProvider }]).map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-400">Provider TTS</label>
          <select
            value={ttsProvider}
            onChange={(e) => setTtsProvider(e.target.value)}
            className="mt-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          >
            {(ttsProviders ?? [{ id: ttsProvider, name: ttsProvider }]).map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        <button
          onClick={run}
          disabled={loading || selectedLocales.size === 0}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {loading ? "Đang ước tính..." : "Ước tính chi phí"}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {estimate && (
        <div className="space-y-3">
          <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-3 py-2">Video</th>
                  <th className="px-3 py-2">Locale</th>
                  <th className="px-3 py-2">Ký tự nguồn</th>
                  <th className="px-3 py-2">Ký tự dịch (ước)</th>
                  <th className="px-3 py-2">Audio (ước)</th>
                  <th className="px-3 py-2">$ dịch</th>
                  <th className="px-3 py-2">$ TTS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {estimate.items.map((it, i) => (
                  <tr key={i}>
                    <td className="px-3 py-2">{it.filename}</td>
                    <td className="px-3 py-2">{it.locale}</td>
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                      {it.source_chars_measured ? "" : "~"}
                      {it.source_chars}
                    </td>
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                      {it.translated_chars_estimate}
                    </td>
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                      {it.tts_audio_seconds_estimate.toFixed(1)}s
                    </td>
                    <td className="px-3 py-2">${it.translation_cost_usd.toFixed(4)}</td>
                    <td className="px-3 py-2">
                      ${it.tts_cost_usd.toFixed(4)}
                      {it.already_done && (
                        <span className="ml-2 text-xs text-slate-400">(đã chạy — có thể cache-hit)</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-sm">
            <span className="font-medium">Tổng cộng: ${estimate.total_cost_usd.toFixed(4)}</span>{" "}
            <span className="text-slate-400">
              (dịch ${estimate.total_translation_cost_usd.toFixed(4)} + TTS $
              {estimate.total_tts_cost_usd.toFixed(4)}, {estimate.total_tts_audio_seconds.toFixed(1)}s audio)
            </span>
          </p>

          {estimate.warnings.length > 0 && (
            <ul className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              {estimate.warnings.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

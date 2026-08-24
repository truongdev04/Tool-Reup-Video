"use client";

import type { WorkspaceUnit } from "@/lib/api";

/** Ngưỡng mặc định `Settings.max_cumulative_drift_ms` (DoD §21) — hiển thị
 * làm mốc tham chiếu, không đọc từ API (dashboard chưa có endpoint settings,
 * xem tech-debt.md). */
const DEFAULT_THRESHOLD_MS = 300;

/**
 * Thanh timeline drift theo từng segment (§19: "hiển thị drift_ms theo từng
 * segment dưới dạng thanh timeline — nhìn ra ngay chỗ trôi"). Trục X = thứ
 * tự unit, trục Y = cumulative_drift_ms — vượt ngưỡng ±300ms tô đỏ.
 */
export default function DriftTimeline({ units }: { units: WorkspaceUnit[] }) {
  const points = units
    .map((u) => ({ idx: u.idx, cumulative: u.drift?.cumulative_drift_ms ?? 0 }))
    .filter((_, i) => units[i].drift !== null);

  if (points.length === 0) {
    return <p className="text-sm text-slate-400">Chưa có dữ liệu drift (chạy stage tts trước).</p>;
  }

  const maxAbs = Math.max(DEFAULT_THRESHOLD_MS, ...points.map((p) => Math.abs(p.cumulative)));
  const width = Math.max(320, points.length * 36);
  const height = 120;
  const midY = height / 2;
  const scale = (midY - 12) / maxAbs;
  const thresholdY = midY - DEFAULT_THRESHOLD_MS * scale;
  const negThresholdY = midY + DEFAULT_THRESHOLD_MS * scale;

  const x = (i: number) => 20 + (i * (width - 40)) / Math.max(1, points.length - 1);
  const y = (v: number) => midY - v * scale;

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.cumulative)}`).join(" ");
  const worstOver = points.some((p) => Math.abs(p.cumulative) > DEFAULT_THRESHOLD_MS);

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} className="min-w-full">
        {/* vùng an toàn */}
        <rect
          x={0}
          y={thresholdY}
          width={width}
          height={negThresholdY - thresholdY}
          className="fill-emerald-50 dark:fill-emerald-950/30"
        />
        <line x1={0} y1={midY} x2={width} y2={midY} className="stroke-slate-300 dark:stroke-slate-700" strokeWidth={1} />
        <line x1={0} y1={thresholdY} x2={width} y2={thresholdY} className="stroke-amber-400" strokeDasharray="4 3" strokeWidth={1} />
        <line x1={0} y1={negThresholdY} x2={width} y2={negThresholdY} className="stroke-amber-400" strokeDasharray="4 3" strokeWidth={1} />
        <path d={path} fill="none" className={worstOver ? "stroke-red-500" : "stroke-emerald-600"} strokeWidth={2} />
        {points.map((p, i) => (
          <circle
            key={p.idx}
            cx={x(i)}
            cy={y(p.cumulative)}
            r={3.5}
            className={Math.abs(p.cumulative) > DEFAULT_THRESHOLD_MS ? "fill-red-500" : "fill-emerald-600"}
          >
            <title>{`unit #${p.idx}: cumulative drift ${p.cumulative}ms`}</title>
          </circle>
        ))}
      </svg>
      <p className="mt-1 text-xs text-slate-400">
        Vùng xanh = trong ngưỡng ±{DEFAULT_THRESHOLD_MS}ms. Chấm đỏ = vượt ngưỡng, cần xem lại (§21).
      </p>
    </div>
  );
}

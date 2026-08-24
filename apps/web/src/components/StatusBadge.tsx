const COLORS: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  pending: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  cancelled: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
  needs_review: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  pass: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  warn: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  fail: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

export default function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

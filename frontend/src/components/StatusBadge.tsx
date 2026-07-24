import { STATUS_COLOR } from "../lib/types";

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLOR[status] || "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

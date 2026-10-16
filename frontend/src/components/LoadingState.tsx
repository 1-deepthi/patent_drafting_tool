// Shared loading indicator — every loading state in the app renders through
// here so loading UI is centred and consistent instead of a ragged
// left-aligned "Loading…" paragraph. Full-page and panel loads get the
// centred block; tight inline slots (list headers, table cells) use compact.

interface LoadingStateProps {
  label?: string;
  compact?: boolean;
}

export function LoadingState({ label = "Loading…", compact = false }: LoadingStateProps) {
  if (compact) {
    return (
      <p role="status" className="py-2 text-center text-xs text-slate-400">
        {label}
      </p>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center justify-center gap-3 py-12 text-center"
    >
      <span
        aria-hidden="true"
        className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600"
      />
      <p className="text-sm text-slate-500">{label}</p>
    </div>
  );
}

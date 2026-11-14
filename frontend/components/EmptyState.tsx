export function EmptyState({
  title,
  description,
  status = "Not yet implemented",
}: {
  title: string;
  description: string;
  status?: string;
}) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface)] p-6">
      <span className="inline-flex items-center rounded-full bg-[var(--color-accent-soft)] px-2.5 py-0.5 text-[11px] font-medium text-[var(--color-accent)]">
        {status}
      </span>
      <h3 className="text-[15px] font-semibold text-[var(--color-ink)]">{title}</h3>
      <p className="max-w-md text-sm leading-relaxed text-[var(--color-ink-muted)]">{description}</p>
    </div>
  );
}

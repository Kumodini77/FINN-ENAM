export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-5 md:px-8 md:py-6">
      <h1 className="text-[20px] font-semibold tracking-tight text-[var(--color-ink)] md:text-[22px]">
        {title}
      </h1>
      {subtitle && (
        <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{subtitle}</p>
      )}
    </div>
  );
}

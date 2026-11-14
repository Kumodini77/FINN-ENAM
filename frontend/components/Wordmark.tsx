export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect width="24" height="24" rx="6" className="fill-[var(--color-accent)]" />
        <path
          d="M7 17V7h8.5M7 12.2h6.2"
          stroke="var(--color-surface)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-[17px] font-semibold tracking-tight text-[var(--color-ink)]">
        FINN
      </span>
    </div>
  );
}

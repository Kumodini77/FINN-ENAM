import { AlertsConfigForm } from "@/components/AlertsConfigForm";
import { AlertsList } from "@/components/AlertsList";
import { PageHeader } from "@/components/PageHeader";

export default function AlertsPage() {
  return (
    <div>
      <PageHeader
        title="Alerts & Settings"
        subtitle="What's crossed your thresholds, and what you want FINN to watch for."
      />
      <div className="space-y-6 p-4 md:p-8">
        <section>
          <h2 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
            Triggered alerts
          </h2>
          <AlertsList />
        </section>
        <section>
          <h2 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
            Configuration
          </h2>
          <AlertsConfigForm />
        </section>
      </div>
    </div>
  );
}

import { AlertsConfigForm } from "@/components/AlertsConfigForm";
import { AlertsList } from "@/components/AlertsList";
import { PageHeader } from "@/components/PageHeader";

export default function AlertsPage() {
  return (
    <div>
      <PageHeader title="Alerts" />
      <div className="space-y-8 p-4 md:p-8">
        <AlertsList />
        <AlertsConfigForm />
      </div>
    </div>
  );
}

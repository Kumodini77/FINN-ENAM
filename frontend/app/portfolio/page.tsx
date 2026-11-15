import { PageHeader } from "@/components/PageHeader";
import { PortfolioTable } from "@/components/PortfolioTable";

export default function PortfolioPage() {
  return (
    <div>
      <PageHeader title="Portfolio" />
      <div className="p-4 md:p-8">
        <PortfolioTable />
      </div>
    </div>
  );
}

import { PageHeader } from "@/components/PageHeader";
import { PortfolioTable } from "@/components/PortfolioTable";

export default function PortfolioPage() {
  return (
    <div>
      <PageHeader
        title="Portfolio"
        subtitle="15 tracked companies · end-of-day price & volume via yfinance"
      />
      <div className="p-4 md:p-8">
        <PortfolioTable />
      </div>
    </div>
  );
}

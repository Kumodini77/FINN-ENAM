import { Suspense } from "react";
import { PageHeader } from "@/components/PageHeader";
import { ResearchAskForm } from "@/components/ResearchAskForm";

async function ResearchFormWithParams({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string; question?: string }>;
}) {
  const params = await searchParams;
  return <ResearchAskForm initialTicker={params.ticker} initialQuestion={params.question} />;
}

export default function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string; question?: string }>;
}) {
  return (
    <div>
      <PageHeader
        title="Research"
        subtitle="Pull: ask about a company, grounded strictly in its own filings — no outside sources, no fabricated figures."
      />
      <div className="p-4 md:p-8">
        <Suspense fallback={<ResearchAskForm />}>
          <ResearchFormWithParams searchParams={searchParams} />
        </Suspense>
      </div>
    </div>
  );
}

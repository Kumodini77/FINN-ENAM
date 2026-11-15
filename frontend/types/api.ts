// Mirrors backend/app/schemas/*.py — kept in sync by hand at this project size.

export type SessionStatus = "closed_eod" | "provisional_intraday";

export interface Company {
  ticker: string;
  name: string;
  exchange: string;
  sector: string;
  yfinance_symbol: string;
  is_seed_portfolio: boolean;
}

export interface CompanyListResponse {
  companies: Company[];
  count: number;
}

export interface PriceQuote {
  ticker: string;
  yfinance_symbol: string;
  data_available: boolean;
  as_of_date: string | null;
  session_status: SessionStatus | null;
  latest_close: number | null;
  previous_close: number | null;
  daily_change_pct: number | null;
  latest_volume: number | null;
  avg_volume_window_days: number | null;
  avg_volume: number | null;
  volume_multiple: number | null;
  fetched_at: string;
  error: string | null;
}

export interface PortfolioQuotesResponse {
  quotes: PriceQuote[];
  calculation_notes: string;
}

export interface DailyBar {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  session_status: SessionStatus;
}

export interface PriceHistoryResponse {
  ticker: string;
  data_available: boolean;
  bars: DailyBar[];
  error: string | null;
}

export interface PulseItem {
  ticker: string;
  metric: "daily" | "five_session" | "twenty_session" | "volume";
  pct_change: number | null;
  volume_multiple: number | null;
  direction: "positive" | "negative";
  observation_date: string;
  latest_close: number;
  note: string;
}

export interface MarketPulseResponse {
  items: PulseItem[];
  calculation_notes: string;
  as_of: string;
}

export type AnnouncementCategory =
  | "results"
  | "M&A"
  | "fund_raise"
  | "management_change"
  | "litigation"
  | "insider_trading"
  | "earnings_call"
  | "investor_meetings"
  | "credit_rating"
  | "dividend"
  | "bonus_split"
  | "capex"
  | "press_release"
  | "postal_ballot"
  | "agm_egm"
  | "pledging"
  | "unclassified";

export const ALL_ANNOUNCEMENT_CATEGORIES: AnnouncementCategory[] = [
  "results",
  "M&A",
  "fund_raise",
  "management_change",
  "litigation",
  "insider_trading",
  "earnings_call",
  "investor_meetings",
  "credit_rating",
  "dividend",
  "bonus_split",
  "capex",
  "press_release",
  "postal_ballot",
  "agm_egm",
  "pledging",
  "unclassified",
];

export type PriorityLevel = "high" | "medium" | "low";

export interface DigestItem {
  id: string;
  company_ticker: string;
  title: string;
  category: AnnouncementCategory;
  priority: PriorityLevel;
  priority_score: number;
  one_line_summary: string | null;
  why_it_matters: string | null;
  filed_at: string;
  ingested_at: string;
  original_source_url: string;
  document_url: string | null;
  verification_status: "verified" | "unverified";
  source: "live" | "cached" | "manual_seed";
  collapsed: boolean;
}

export interface DigestResponse {
  window_start: string;
  window_end: string;
  total_count: number;
  collapsed_count: number;
  items: DigestItem[];
}

export interface Alert {
  id: string;
  company_ticker: string;
  trigger_type: "volume_spike" | "price_move" | "material_announcement";
  source_announcement_id: string | null;
  trade_date: string | null;
  payload: Record<string, unknown>;
  triggered_at: string;
  seen_at: string | null;
  transparency: AlertTransparency;
}

export interface AlertsConfig {
  user_id: string;
  volume_spike_multiple: number;
  price_move_pct: number;
  digest_window_hours: number;
  alert_categories: AnnouncementCategory[];
  updated_at: string;
}

export interface AnnouncementImportRequest {
  ticker: string;
  title: string;
  filed_at: string;
  original_source_url: string;
  document_url?: string | null;
  extracted_text?: string | null;
  category?: AnnouncementCategory | null;
  source?: "live" | "cached" | "manual_seed";
  verification_status?: "verified" | "unverified";
  seeded_by?: string | null;
}

export interface AnnouncementImportResult {
  announcement_id: string;
  created: boolean;
  category: AnnouncementCategory;
  priority: string;
  priority_score: number;
  message: string;
}

export type ChunkType = "prose" | "table_row_group" | "table_unparsed";

export interface HybridEvidenceChunk {
  chunk_id: string;
  document_id: string;
  company_id: string;
  company_ticker: string;
  chunk_text: string;
  chunk_type: ChunkType;
  needs_manual_review: boolean;
  page_reference: number | null;
  section_label: string | null;
  doc_type: string | null;
  reporting_period: string | null;
  original_source_url: string | null;
  matched_via: string[];
  relevance_score: number;
  vector_distance: number | null;
  lexical_match_terms: string[];
}

export interface NumericAnswer {
  metric_label: string;
  period_label: string | null;
  value: string;
  all_values_for_row: string[];
  ambiguous_period_binding: boolean;
  header_line: string;
  source_chunk_id: string;
  source_document_id: string;
  page_reference: number | null;
  original_source_url: string | null;
  reporting_period: string | null;
  extraction_method: string;
  unit_scale: string | null;
  normalized_value: string | null;
}

export type ResearchAnswerType = "numeric_fact" | "evidence_digest" | "insufficient_evidence" | "ambiguous_metric";

export interface SourceDocument {
  announcement_id: string;
  title: string;
  category: AnnouncementCategory;
  filed_at: string;
  original_source_url: string;
  document_url: string | null;
}

export type ChangeDirection = "positive" | "negative" | "not_available" | "not_comparable";

export interface FinancialChange {
  metric: string;
  label: string;
  latest_value: number | null;
  comparison_value: number | null;
  qoq_pct: number | null;
  yoy_pct: number | null;
  direction: ChangeDirection;
  unit: string;
  currency: string;
  basis: string;
  comparison_period: string | null;
  not_comparable_reason: string | null;
}

export interface ResearchLink {
  ticker: string;
  suggested_question: string;
}

export interface EventItem {
  company_ticker: string;
  event_category: AnnouncementCategory;
  event_date: string;
  reporting_period: string | null;
  priority: PriorityLevel;
  priority_rationale: string;
  why_it_matters: string;
  financial_changes: FinancialChange[];
  basis_mismatch_warnings: string[];
  missing_information: string[];
  source_documents: SourceDocument[];
  research_link: ResearchLink;
}

export interface EventsResponse {
  window_start: string;
  window_end: string;
  events: EventItem[];
  total_announcements: number;
}

export interface AlertTransparency {
  is_primary_disclosure: boolean;
  has_numerical_evidence: boolean;
  evidence_note: string;
  priority_rationale: string | null;
}

export interface ResearchAskResponse {
  company_ticker: string;
  company_id: string;
  question: string;
  intents: string[];
  answer_type: ResearchAnswerType;
  numeric_answer: NumericAnswer | null;
  evidence: HybridEvidenceChunk[];
  insufficient_evidence_reason: string | null;
  metric_alternatives: string[] | null;
  generation_note: string;
}

import type {
  Alert,
  AlertsConfig,
  AnnouncementCategory,
  AnnouncementImportRequest,
  AnnouncementImportResult,
  CompanyListResponse,
  DigestResponse,
  EventsResponse,
  MarketPulseResponse,
  PortfolioQuotesResponse,
  PriceHistoryResponse,
  PriceQuote,
  ResearchAskResponse,
} from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api";

class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("Could not reach the FINN API. Is the backend running?", 0);
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = body?.error?.message ? ` — ${body.error.message}` : "";
    } catch {
      // response wasn't JSON; ignore
    }
    throw new ApiError(`Request to ${path} failed with status ${res.status}${detail}`, res.status);
  }
  return res.json() as Promise<T>;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export async function fetchCompanies(portfolioOnly = false): Promise<CompanyListResponse> {
  return request<CompanyListResponse>(`/companies${portfolioOnly ? "?portfolio_only=true" : ""}`);
}

export async function fetchPortfolioQuotes(): Promise<PortfolioQuotesResponse> {
  return request<PortfolioQuotesResponse>("/market-data/portfolio");
}

export async function fetchQuote(ticker: string): Promise<PriceQuote> {
  return request<PriceQuote>(`/market-data/${ticker}`);
}

export async function fetchPriceHistory(ticker: string, days = 30): Promise<PriceHistoryResponse> {
  return request<PriceHistoryResponse>(`/market-data/${ticker}/history?days=${days}`);
}

export async function fetchMarketPulse(): Promise<MarketPulseResponse> {
  return request<MarketPulseResponse>("/market-data/portfolio/pulse");
}

export async function fetchDigest(params: {
  windowHours?: number;
  start?: string;
  end?: string;
  categories?: AnnouncementCategory[];
}): Promise<DigestResponse> {
  const q = new URLSearchParams();
  if (params.windowHours !== undefined) q.set("window_hours", String(params.windowHours));
  if (params.start) q.set("start", params.start);
  if (params.end) q.set("end", params.end);
  for (const c of params.categories ?? []) q.append("categories", c);
  return request<DigestResponse>(`/digest?${q.toString()}`);
}

export async function fetchAlerts(): Promise<Alert[]> {
  return request<Alert[]>("/alerts");
}

export async function fetchAlertsConfig(): Promise<AlertsConfig> {
  return request<AlertsConfig>("/alerts/config");
}

export async function saveAlertsConfig(config: {
  volume_spike_multiple: number;
  price_move_pct: number;
  digest_window_hours: number;
  alert_categories: AnnouncementCategory[];
}): Promise<AlertsConfig> {
  return request<AlertsConfig>("/alerts/config", jsonInit("PUT", config));
}

export async function importAnnouncement(payload: AnnouncementImportRequest): Promise<AnnouncementImportResult> {
  return request<AnnouncementImportResult>("/announcements/import", jsonInit("POST", payload));
}

export interface AnnouncementImportBatchResult {
  results: AnnouncementImportResult[];
  created_count: number;
  duplicate_count: number;
  error_count: number;
  errors: string[];
}

export async function importAnnouncementsBatch(
  payloads: AnnouncementImportRequest[]
): Promise<AnnouncementImportBatchResult> {
  return request<AnnouncementImportBatchResult>("/announcements/import/batch", jsonInit("POST", payloads));
}

export async function fetchEvents(params: {
  windowHours?: number;
  start?: string;
  end?: string;
  categories?: AnnouncementCategory[];
}): Promise<EventsResponse> {
  const q = new URLSearchParams();
  if (params.windowHours !== undefined) q.set("window_hours", String(params.windowHours));
  if (params.start) q.set("start", params.start);
  if (params.end) q.set("end", params.end);
  for (const c of params.categories ?? []) q.append("categories", c);
  return request<EventsResponse>(`/events?${q.toString()}`);
}

export async function askResearch(ticker: string, question: string): Promise<ResearchAskResponse> {
  const q = new URLSearchParams({ ticker, question });
  return request<ResearchAskResponse>(`/research/ask?${q.toString()}`);
}

export { ApiError };

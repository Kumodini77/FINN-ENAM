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

// In-memory, per-browser-tab response cache with a short, explicit TTL per
// endpoint — NOT a general cache for every GET. Only applied to data that is
// genuinely safe to reuse for a few seconds (company metadata, EOD price
// history, EOD quotes): nothing time-sensitive like alerts, events, digest
// or research answers goes through this, so "cached" data is never silently
// shown where freshness actually matters. Concurrent callers for the same
// key share one in-flight request instead of firing duplicates (the N+1
// per-company history fetch on the portfolio page is the case this exists
// for).
const _cache = new Map<string, { expiresAt: number; value: unknown }>();
const _inFlight = new Map<string, Promise<unknown>>();

async function cachedRequest<T>(path: string, ttlMs: number): Promise<T> {
  const cached = _cache.get(path);
  if (cached && cached.expiresAt > Date.now()) return cached.value as T;

  const pending = _inFlight.get(path);
  if (pending) return pending as Promise<T>;

  const promise = request<T>(path)
    .then((value) => {
      _cache.set(path, { expiresAt: Date.now() + ttlMs, value });
      return value;
    })
    .finally(() => _inFlight.delete(path));
  _inFlight.set(path, promise);
  return promise as Promise<T>;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

// TTLs: company metadata rarely changes within a session; EOD price/quote
// data is finalized once per trading day, so a short cache never shows data
// older than what the backend itself would return anyway — it just avoids
// re-fetching it on every page visit within that window.
const COMPANY_LIST_TTL_MS = 5 * 60_000;
const QUOTES_TTL_MS = 45_000;
const HISTORY_TTL_MS = 5 * 60_000;
const PULSE_TTL_MS = 45_000;

export async function fetchCompanies(portfolioOnly = false): Promise<CompanyListResponse> {
  return cachedRequest<CompanyListResponse>(`/companies${portfolioOnly ? "?portfolio_only=true" : ""}`, COMPANY_LIST_TTL_MS);
}

export async function fetchPortfolioQuotes(): Promise<PortfolioQuotesResponse> {
  return cachedRequest<PortfolioQuotesResponse>("/market-data/portfolio", QUOTES_TTL_MS);
}

export async function fetchQuote(ticker: string): Promise<PriceQuote> {
  return cachedRequest<PriceQuote>(`/market-data/${ticker}`, QUOTES_TTL_MS);
}

export async function fetchPriceHistory(ticker: string, days = 30): Promise<PriceHistoryResponse> {
  return cachedRequest<PriceHistoryResponse>(`/market-data/${ticker}/history?days=${days}`, HISTORY_TTL_MS);
}

export async function fetchMarketPulse(): Promise<MarketPulseResponse> {
  return cachedRequest<MarketPulseResponse>("/market-data/portfolio/pulse", PULSE_TTL_MS);
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

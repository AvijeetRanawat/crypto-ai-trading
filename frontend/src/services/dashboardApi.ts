import { API_BASE } from "../utils/constants";
import type {
  IntentData,
  Lesson,
  LlmSummary,
  MarketPoint,
  PortfolioSummary,
  RegimeData,
  SessionStartResponse,
  SignalEvent,
  Trade,
  WarmupData,
} from "../types/dashboard";

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(path);
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export const dashboardApi = {
  sessionStart: () => fetchJson<SessionStartResponse>(`${API_BASE}/session_start`),
  warmup: () => fetchJson<WarmupData>(`${API_BASE}/warmup`),
  marketHistory: (symbol: string) =>
    fetchJson<MarketPoint[]>(`${API_BASE}/market/history?symbol=${encodeURIComponent(symbol)}`),
  portfolioSummary: () => fetchJson<PortfolioSummary>(`${API_BASE}/portfolio/summary`),
  intent: () => fetchJson<IntentData>(`${API_BASE}/intent`),
  signals: (symbol: string, limit = 60) =>
    fetchJson<SignalEvent[]>(
      `${API_BASE}/signals/history?symbol=${encodeURIComponent(symbol)}&limit=${limit}`,
    ),
  regime: () => fetchJson<RegimeData>(`${API_BASE}/regime`),
  tradesRecent: () => fetchJson<Trade[]>(`${API_BASE}/trades/recent`),
  lessons: () => fetchJson<Lesson[]>(`${API_BASE}/lessons`),
  logs: (lines = 60) => fetchJson<{ logs: string[] }>(`${API_BASE}/logs?lines=${lines}`),
  llmSummary: () => fetchJson<LlmSummary>(`${API_BASE}/llm/summary`),
};

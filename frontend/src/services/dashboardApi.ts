import { API_BASE } from "../utils/constants";
import type {
  IntentData,
  LlmBreakdown,
  Lesson,
  LlmSummary,
  MarketPoint,
  NewsSentiment,
  PortfolioBalances,
  PortfolioSummary,
  RlCostSummary,
  RlTuningSnapshot,
  RlWeightsSnapshot,
  RegimeData,
  SessionStartResponse,
  SignalEvent,
  StrategyDiagnostics,
  Trade,
  WarmupData,
} from "../types/dashboard";

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(path, {
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
      },
    });
    if (!response.ok) {
      console.warn(`[dashboardApi] GET ${path} returned ${response.status}`);
      return null;
    }
    return (await response.json()) as T;
  } catch (err) {
    console.warn(`[dashboardApi] GET ${path} failed`, err);
    return null;
  }
}

async function putJson<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const response = await fetch(path, {
      method: "PUT",
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      console.warn(`[dashboardApi] PUT ${path} returned ${response.status}`);
      return null;
    }
    return (await response.json()) as T;
  } catch (err) {
    console.warn(`[dashboardApi] PUT ${path} failed`, err);
    return null;
  }
}

export const dashboardApi = {
  sessionStart: () => fetchJson<SessionStartResponse>(`${API_BASE}/session_start`),
  warmup: (symbol: string) =>
    fetchJson<WarmupData>(`${API_BASE}/warmup?symbol=${encodeURIComponent(symbol)}`),
  marketHistory: (symbol: string) =>
    fetchJson<MarketPoint[]>(`${API_BASE}/market/history?symbol=${encodeURIComponent(symbol)}`),
  portfolioSummary: () => fetchJson<PortfolioSummary>(`${API_BASE}/portfolio/summary`),
  portfolioBalances: () => fetchJson<PortfolioBalances>(`${API_BASE}/portfolio/balances`),
  intent: (mode?: string) =>
    fetchJson<IntentData>(
      `${API_BASE}/intent${mode ? `?mode=${encodeURIComponent(mode)}` : ""}`,
    ),
  signals: (symbol: string, limit = 60) =>
    fetchJson<SignalEvent[]>(
      `${API_BASE}/signals/history?symbol=${encodeURIComponent(symbol)}&limit=${limit}`,
    ),
  regime: (symbol: string) =>
    fetchJson<RegimeData>(`${API_BASE}/regime?symbol=${encodeURIComponent(symbol)}`),
  tradesRecent: () => fetchJson<Trade[]>(`${API_BASE}/trades/recent`),
  lessons: () => fetchJson<Lesson[]>(`${API_BASE}/lessons`),
  logs: (lines = 60) => fetchJson<{ logs: string[] }>(`${API_BASE}/logs?lines=${lines}`),
  llmSummary: () => fetchJson<LlmSummary>(`${API_BASE}/llm/summary`),
  llmBreakdown: () => fetchJson<LlmBreakdown>(`${API_BASE}/llm/breakdown`),
  rlCost: () => fetchJson<RlCostSummary>(`${API_BASE}/rl/cost`),
  rlWeights: () => fetchJson<RlWeightsSnapshot>(`${API_BASE}/rl/weights`),
  rlTuning: () => fetchJson<RlTuningSnapshot>(`${API_BASE}/config/rl-tuning`),
  updateRlTuning: (values: Record<string, number | boolean | null>) =>
    putJson<RlTuningSnapshot>(`${API_BASE}/config/rl-tuning`, { values }),
  strategyDiagnostics: (symbol: string, mode: string) =>
    fetchJson<StrategyDiagnostics>(
      `${API_BASE}/strategy/diagnostics?symbol=${encodeURIComponent(symbol)}&mode=${encodeURIComponent(mode)}`,
    ),
  newsSentiment: (symbol: string) =>
    fetchJson<NewsSentiment>(`${API_BASE}/news/sentiment?symbol=${encodeURIComponent(symbol)}`),
};

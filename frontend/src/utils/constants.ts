export const API_BASE = "/api";

export const STORAGE_KEYS = {
  theme: "dashboard-theme",
  panelWidth: "ai-panel-width",
  sessionStart: "tradingSessionStart",
  sessionStartMs: "tradingSessionStartMs",
} as const;

export const TOTAL_VOTES = 8;

export const SUPPORTED_SYMBOLS = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "ETHBTC",
  "SOLBTC",
  "SOLETH",
] as const;

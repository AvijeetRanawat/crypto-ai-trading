export const API_BASE = "/api";

export const STORAGE_KEYS = {
  theme: "dashboard-theme",
  panelWidth: "ai-panel-width",
  logsHeight: "logs-height",
  tradingMode: "trading-mode",
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

export const TRADING_MODES = ["SPOT", "FUTURES", "OPTIONS"] as const;
export type TradingMode = (typeof TRADING_MODES)[number];

export const SYMBOLS_BY_TRADING_MODE: Record<TradingMode, readonly string[]> = {
  SPOT: SUPPORTED_SYMBOLS,
  FUTURES: SUPPORTED_SYMBOLS,
  OPTIONS: SUPPORTED_SYMBOLS,
};

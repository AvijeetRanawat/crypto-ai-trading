export interface SessionStartResponse {
  session_start: string;
  session_start_ms: number;
}

export interface WarmupData {
  done: boolean;
  ticks: number;
  min_ticks: number;
  pct: number;
  seconds_remaining: number;
}

export interface MarketPoint {
  timestamp: string;
  price: number;
}

export interface OpenPosition {
  symbol: string;
  side: string;
  entry_price: number;
  entry_time: string;
}

export interface PortfolioSummary {
  total_pnl: number;
  win_rate: number;
  total_trades: number;
  missed_count: number;
  traded_signals: number;
  llm_cost_today: number;
  llm_calls_today: number;
  llm_cost_session: number;
  llm_calls_session: number;
  llm_tokens_session: number;
  llm_decision_calls_session: number;
  llm_cost_per_traded_signal: number | null;
  llm_cost_per_dollar_pnl: number | null;
  llm_trade_conversion_rate: number;
  open_position: OpenPosition | null;
}

export interface SignalEvent {
  timestamp: string;
  price: number;
  buy_votes: number;
  sell_votes: number;
  rsi: number;
  macd: string;
  bb_pct: number;
  outcome: string;
  claude_action: string;
  claude_conf: number;
}

export interface Trade {
  id: number;
  symbol: string;
  side: string;
  price: number;
  quantity: number;
  entry_time: string;
  exit_time: string | null;
  reason: string;
  pnl: number;
  status: string;
}

export interface Lesson {
  id: number;
  timestamp: string;
  condition: string;
  lesson: string;
  severity: string;
}

export interface IntentData {
  message: string;
  targets: string[];
  timestamp?: string;
}

export interface RegimeData {
  regime: string;
  strength?: number;
  ema20?: number;
  ema50?: number;
  trade_direction?: string;
  verdict: string;
  atr_sl?: number;
  atr_tp?: number;
  atr_verdict: string;
  session: string;
  session_quality: string;
  session_verdict: string;
}

export interface LlmSummary {
  llm_cost_session: number;
  llm_calls_session: number;
  llm_tokens_session: number;
  llm_cost_today: number;
  llm_calls_today: number;
  llm_tokens_today: number;
  llm_cost_all_time: number;
  llm_calls_all_time: number;
  llm_tokens_all_time: number;
  llm_decision_calls_session: number;
  traded_signals: number;
  llm_trade_conversion_rate: number;
}

export interface LlmModelUsage {
  model_id: string;
  calls: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface LlmBreakdown {
  session: LlmModelUsage[];
  today: LlmModelUsage[];
  all_time: LlmModelUsage[];
}

export interface NewsHeadline {
  source: string;
  title: string;
  url: string;
  published_at: string | null;
  sentiment_score: number;
}

export interface NewsSentiment {
  updated_at: string;
  symbol: string;
  sentiment_score: number;
  sentiment_label: string;
  components: {
    news_score: number;
    fear_greed_score: number;
    fear_greed: {
      value: number | null;
      value_classification: string;
      sentiment_score: number;
      timestamp?: string;
    };
    articles_count: number;
    sources_available: Record<string, boolean>;
  };
  articles: NewsHeadline[];
  llm_summary?: {
    text: string;
    model_id: string;
    timestamp: string;
    cached: boolean;
  };
}

export const DEFAULT_WARMUP: WarmupData = {
  done: false,
  ticks: 0,
  min_ticks: 35,
  pct: 0,
  seconds_remaining: 0,
};

export const DEFAULT_SUMMARY: PortfolioSummary = {
  total_pnl: 0,
  win_rate: 0,
  total_trades: 0,
  missed_count: 0,
  traded_signals: 0,
  llm_cost_today: 0,
  llm_calls_today: 0,
  llm_cost_session: 0,
  llm_calls_session: 0,
  llm_tokens_session: 0,
  llm_decision_calls_session: 0,
  llm_cost_per_traded_signal: null,
  llm_cost_per_dollar_pnl: null,
  llm_trade_conversion_rate: 0,
  open_position: null,
};

export const DEFAULT_INTENT: IntentData = {
  message: "Initializing...",
  targets: [],
};

export const DEFAULT_REGIME: RegimeData = {
  regime: "WARMING_UP",
  verdict: "Loading...",
  atr_verdict: "ATR: -",
  session: "-",
  session_quality: "LOW",
  session_verdict: "Loading session window...",
};

export const DEFAULT_LLM_SUMMARY: LlmSummary = {
  llm_cost_session: 0,
  llm_calls_session: 0,
  llm_tokens_session: 0,
  llm_cost_today: 0,
  llm_calls_today: 0,
  llm_tokens_today: 0,
  llm_cost_all_time: 0,
  llm_calls_all_time: 0,
  llm_tokens_all_time: 0,
  llm_decision_calls_session: 0,
  traded_signals: 0,
  llm_trade_conversion_rate: 0,
};

export const DEFAULT_LLM_BREAKDOWN: LlmBreakdown = {
  session: [],
  today: [],
  all_time: [],
};

export const DEFAULT_NEWS_SENTIMENT: NewsSentiment = {
  updated_at: "",
  symbol: "BTCUSDT",
  sentiment_score: 0,
  sentiment_label: "NEUTRAL",
  components: {
    news_score: 0,
    fear_greed_score: 0,
    fear_greed: {
      value: null,
      value_classification: "Unknown",
      sentiment_score: 0,
    },
    articles_count: 0,
    sources_available: {},
  },
  articles: [],
  llm_summary: {
    text: "",
    model_id: "gpt-5-nano",
    timestamp: "",
    cached: true,
  },
};

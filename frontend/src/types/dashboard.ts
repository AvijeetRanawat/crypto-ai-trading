export interface SessionStartResponse {
  session_start: string;
  session_start_ms: number;
}

export interface WarmupData {
  symbol?: string;
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
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  quantity: number;
  entry_time: string;
  mode: string;
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
  open_positions: OpenPosition[];
}

export interface SignalEvent {
  timestamp: string;
  price: number;
  buy_votes: number;
  sell_votes: number;
  weighted_buy?: number;
  weighted_sell?: number;
  total_weight?: number;
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

export interface CryptoBalance {
  symbol: string;  // Base asset (BTC, ETH, SOL)
  total_quantity: number;  // Total owned (LONG positions only)
  avg_entry_price: number;  // USD
  current_price: number;  // USD
  cost_basis: number;  // USD
  current_value: number;  // USD
  unrealized_pnl: number;  // USD
  unrealized_pnl_pct: number;
  positions: Array<{
    id: number;
    side: 'LONG';  // Only LONG positions shown
    trading_pair: string;  // e.g. BTCUSDT, ETHUSDT
    quantity: number;  // Positive for owned assets
    entry_price: number;  // USD
    entry_time: string;
    current_price: number;  // USD
    unrealized_pnl: number;  // USD
  }>;
}

export interface PortfolioBalances {
  balances: CryptoBalance[];
  total_unrealized_pnl: number;
  total_cost_basis: number;
  total_current_value: number;
}

export interface IntentData {
  message: string;
  targets: string[];
  timestamp?: string;
}

export interface RegimeData {
  symbol?: string;
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

export interface StrategyDecision {
  timestamp: string;
  outcome: string;
  decision_source: string;
  action: string;
  confidence: number;
  buy_votes: number;
  sell_votes: number;
  weighted_buy?: number;
  weighted_sell?: number;
  total_weight?: number;
}

export interface StrategyDiagnostics {
  symbol: string;
  mode: string;
  strategy_note: string;
  session_signals: {
    total: number;
    traded: number;
    missed: number;
    skipped: number;
  };
  session_trades: {
    closed: number;
    wins: number;
    win_rate: number;
    avg_pnl: number;
    total_pnl: number;
  };
  latest_trade_reason: string;
  recent_decisions: StrategyDecision[];
}

export interface RlCostBucket {
  events: number;
  skip_penalty: number;
  hold_penalty: number;
  total_penalty: number;
  total_reward: number;
}

export interface RlCostEvent {
  timestamp: string;
  event_type: string;
  mode: string;
  symbol: string;
  profile_id: string;
  reason: string;
  reward: number;
  penalty: number;
}

export interface RlCostSummary {
  session: RlCostBucket;
  today: RlCostBucket;
  all_time: RlCostBucket;
  recent: RlCostEvent[];
}

export interface RlProfileConfig {
  weight_mult?: Record<string, number>;
  voter_weight_mult?: Record<string, number>;
  size_mult?: number;
  leverage_mult?: number;
  confidence_bias?: number;
  sentiment_gate_mult?: number;
}

export interface RlLearnedProfile {
  profile_id: string;
  q: number;
  n: number;
}

export interface RlLearnedState {
  state_key: string;
  total_n: number;
  profiles: RlLearnedProfile[];
}

export interface RlWeightsSnapshot {
  meta: {
    epsilon: number;
    updated_at: string;
  };
  profiles: Record<string, Record<string, RlProfileConfig>>;
  learned: Record<string, RlLearnedState[]>;
  error?: string;
}

export interface RlTuningSetting {
  key: string;
  type: "float" | "int" | "bool";
  default: number | boolean;
  value: number | boolean;
  overridden: boolean;
  min?: number;
  max?: number;
}

export interface RlTuningSnapshot {
  settings: RlTuningSetting[];
  updated_at: string;
  error?: string;
}

export const DEFAULT_WARMUP: WarmupData = {
  symbol: "BTCUSDT",
  done: false,
  ticks: 0,
  min_ticks: 10,
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
  open_positions: [],
};

export const DEFAULT_INTENT: IntentData = {
  message: "Initializing...",
  targets: [],
};

export const DEFAULT_REGIME: RegimeData = {
  symbol: "BTCUSDT",
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
    model_id: "gpt-4.1-mini",
    timestamp: "",
    cached: true,
  },
};

export const DEFAULT_STRATEGY_DIAGNOSTICS: StrategyDiagnostics = {
  symbol: "BTCUSDT",
  mode: "SPOT",
  strategy_note: "Loading strategy diagnostics...",
  session_signals: {
    total: 0,
    traded: 0,
    missed: 0,
    skipped: 0,
  },
  session_trades: {
    closed: 0,
    wins: 0,
    win_rate: 0,
    avg_pnl: 0,
    total_pnl: 0,
  },
  latest_trade_reason: "",
  recent_decisions: [],
};

export const DEFAULT_RL_COST_SUMMARY: RlCostSummary = {
  session: {
    events: 0,
    skip_penalty: 0,
    hold_penalty: 0,
    total_penalty: 0,
    total_reward: 0,
  },
  today: {
    events: 0,
    skip_penalty: 0,
    hold_penalty: 0,
    total_penalty: 0,
    total_reward: 0,
  },
  all_time: {
    events: 0,
    skip_penalty: 0,
    hold_penalty: 0,
    total_penalty: 0,
    total_reward: 0,
  },
  recent: [],
};

export const DEFAULT_RL_TUNING: RlTuningSnapshot = {
  settings: [],
  updated_at: "",
};

export const DEFAULT_RL_WEIGHTS: RlWeightsSnapshot = {
  meta: {
    epsilon: 0,
    updated_at: "",
  },
  profiles: {},
  learned: {
    SPOT: [],
    FUTURES: [],
    OPTIONS: [],
  },
};

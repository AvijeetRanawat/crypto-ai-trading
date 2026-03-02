import { useCallback, useEffect, useRef, useState } from "react";
import { dashboardApi } from "../services/dashboardApi";
import {
  DEFAULT_INTENT,
  DEFAULT_LLM_BREAKDOWN,
  DEFAULT_RL_COST_SUMMARY,
  DEFAULT_RL_TUNING,
  DEFAULT_RL_WEIGHTS,
  DEFAULT_LLM_SUMMARY,
  DEFAULT_NEWS_SENTIMENT,
  DEFAULT_REGIME,
  DEFAULT_STRATEGY_DIAGNOSTICS,
  DEFAULT_SUMMARY,
  DEFAULT_WARMUP,
  type IntentData,
  type LlmBreakdown,
  type Lesson,
  type LlmSummary,
  type MarketPoint,
  type NewsSentiment,
  type PortfolioBalances,
  type PortfolioSummary,
  type RegimeData,
  type RlCostSummary,
  type RlTuningSnapshot,
  type RlWeightsSnapshot,
  type SignalEvent,
  type StrategyDiagnostics,
  type Trade,
  type WarmupData,
} from "../types/dashboard";
import { STORAGE_KEYS } from "../utils/constants";
import type { TradingMode } from "../utils/constants";

interface DashboardDataState {
  nowMs: number;
  startTimeMs: number;
  warmup: WarmupData;
  marketHistory: MarketPoint[];
  summary: PortfolioSummary;
  balances: PortfolioBalances | null;
  signals: SignalEvent[];
  trades: Trade[];
  lessons: Lesson[];
  intent: IntentData;
  regime: RegimeData;
  logs: string;
  llmSummary: LlmSummary;
  llmBreakdown: LlmBreakdown;
  newsSentiment: NewsSentiment;
  strategyDiagnostics: StrategyDiagnostics;
  rlCostSummary: RlCostSummary;
  rlWeights: RlWeightsSnapshot;
  rlTuning: RlTuningSnapshot;
}

const FAST_POLL_MS = 3000;
const SLOW_POLL_MS = 8000;

export function useDashboardData(symbol = "BTCUSDT", tradingMode: TradingMode = "SPOT"): DashboardDataState {
  const [nowMs, setNowMs] = useState(Date.now());
  const [startTimeMs, setStartTimeMs] = useState<number>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.sessionStartMs);
    return stored ? Number(stored) : Date.now();
  });

  const [warmup, setWarmup] = useState<WarmupData>(DEFAULT_WARMUP);
  const [marketHistory, setMarketHistory] = useState<MarketPoint[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary>(DEFAULT_SUMMARY);
  const [balances, setBalances] = useState<PortfolioBalances | null>(null);
  const [signals, setSignals] = useState<SignalEvent[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [intent, setIntent] = useState<IntentData>(DEFAULT_INTENT);
  const [regime, setRegime] = useState<RegimeData>(DEFAULT_REGIME);
  const [logs, setLogs] = useState("...");
  const [llmSummary, setLlmSummary] = useState<LlmSummary>(DEFAULT_LLM_SUMMARY);
  const [llmBreakdown, setLlmBreakdown] = useState<LlmBreakdown>(DEFAULT_LLM_BREAKDOWN);
  const [newsSentiment, setNewsSentiment] = useState<NewsSentiment>(DEFAULT_NEWS_SENTIMENT);
  const [strategyDiagnostics, setStrategyDiagnostics] = useState<StrategyDiagnostics>(DEFAULT_STRATEGY_DIAGNOSTICS);
  const [rlCostSummary, setRlCostSummary] = useState<RlCostSummary>(DEFAULT_RL_COST_SUMMARY);
  const [rlWeights, setRlWeights] = useState<RlWeightsSnapshot>(DEFAULT_RL_WEIGHTS);
  const [rlTuning, setRlTuning] = useState<RlTuningSnapshot>(DEFAULT_RL_TUNING);

  const sessionStartRef = useRef<string | null>(localStorage.getItem(STORAGE_KEYS.sessionStart));
  const fastPollInFlightRef = useRef(false);
  const slowPollInFlightRef = useRef(false);
  const lastSlowPollAtRef = useRef(0);

  const resetSessionState = useCallback(() => {
    setWarmup({ ...DEFAULT_WARMUP });
    setMarketHistory([]);
    setSignals([]);
    setTrades([]);
    setLessons([]);
    setIntent({ message: "New session starting...", targets: [] });
    setLogs("...");
    setSummary({ ...DEFAULT_SUMMARY });
    setLlmSummary({ ...DEFAULT_LLM_SUMMARY });
    setLlmBreakdown({ ...DEFAULT_LLM_BREAKDOWN });
    setNewsSentiment({ ...DEFAULT_NEWS_SENTIMENT });
    setStrategyDiagnostics({ ...DEFAULT_STRATEGY_DIAGNOSTICS, symbol, mode: tradingMode });
    setRlCostSummary({ ...DEFAULT_RL_COST_SUMMARY });
    setRlWeights({ ...DEFAULT_RL_WEIGHTS });
    setRlTuning({ ...DEFAULT_RL_TUNING });
  }, [symbol, tradingMode]);

  const syncSessionStart = useCallback(async () => {
    const data = await dashboardApi.sessionStart();
    if (!data) return;

    if (!sessionStartRef.current) {
      sessionStartRef.current = data.session_start;
      localStorage.setItem(STORAGE_KEYS.sessionStart, data.session_start);
      localStorage.setItem(STORAGE_KEYS.sessionStartMs, String(data.session_start_ms || Date.now()));
      setStartTimeMs(Number(data.session_start_ms || Date.now()));
      return;
    }

    if (sessionStartRef.current !== data.session_start) {
      sessionStartRef.current = data.session_start;
      localStorage.setItem(STORAGE_KEYS.sessionStart, data.session_start);
      localStorage.setItem(STORAGE_KEYS.sessionStartMs, String(data.session_start_ms || Date.now()));
      setStartTimeMs(Number(data.session_start_ms || Date.now()));
      resetSessionState();
    }
  }, [resetSessionState]);

  useEffect(() => {
    let active = true;

    const fastPoll = async () => {
      if (fastPollInFlightRef.current) return;
      fastPollInFlightRef.current = true;
      try {
        await syncSessionStart();
        if (!active) {
          return;
        }

        const [warm, market, portfolio, portfolioBalances, currentIntent, signalData, regimeData] = await Promise.all([
          dashboardApi.warmup(symbol),
          dashboardApi.marketHistory(symbol),
          dashboardApi.portfolioSummary(),
          dashboardApi.portfolioBalances(),
          dashboardApi.intent(tradingMode),
          dashboardApi.signals(symbol, 60),
          dashboardApi.regime(symbol),
        ]);

        if (!active) return;
        if (warm) setWarmup(warm);
        if (market) setMarketHistory(market);
        if (portfolio) setSummary(portfolio);
        if (portfolioBalances) setBalances(portfolioBalances);
        if (currentIntent) setIntent(currentIntent);
        if (signalData) setSignals(signalData);
        if (regimeData) setRegime(regimeData);
      } finally {
        fastPollInFlightRef.current = false;
      }
    };

    const slowPoll = async () => {
      const now = Date.now();
      if (slowPollInFlightRef.current) return;
      if (now - lastSlowPollAtRef.current < 2000) return;
      slowPollInFlightRef.current = true;
      lastSlowPollAtRef.current = now;
      try {
        const [tradeData, lessonData, logData, usage, breakdown, diagnostics, news, rlCost, rlWeightsData, rlTuningData] = await Promise.all([
          dashboardApi.tradesRecent(),
          dashboardApi.lessons(),
          dashboardApi.logs(120),
          dashboardApi.llmSummary(),
          dashboardApi.llmBreakdown(),
          dashboardApi.strategyDiagnostics(symbol, tradingMode),
          dashboardApi.newsSentiment(symbol),
          dashboardApi.rlCost(),
          dashboardApi.rlWeights(),
          dashboardApi.rlTuning(),
        ]);

        if (!active) return;
        if (tradeData) setTrades(tradeData);
        if (lessonData) setLessons(lessonData);
        if (logData?.logs) setLogs(logData.logs.join("").trim());
        if (usage) setLlmSummary(usage);
        if (breakdown) setLlmBreakdown(breakdown);
        if (diagnostics) setStrategyDiagnostics(diagnostics);
        if (news) setNewsSentiment(news);
        if (rlCost) setRlCostSummary(rlCost);
        if (rlWeightsData) setRlWeights(rlWeightsData);
        if (rlTuningData) setRlTuning(rlTuningData);
      } finally {
        slowPollInFlightRef.current = false;
      }
    };

    fastPoll();
    slowPoll();

    const fastInterval = setInterval(fastPoll, FAST_POLL_MS);
    const slowInterval = setInterval(slowPoll, SLOW_POLL_MS);
    const clockInterval = setInterval(() => setNowMs(Date.now()), 1000);

    return () => {
      active = false;
      clearInterval(fastInterval);
      clearInterval(slowInterval);
      clearInterval(clockInterval);
    };
  }, [symbol, tradingMode, syncSessionStart]);

  return {
    nowMs,
    startTimeMs,
    warmup,
    marketHistory,
    summary,
    balances,
    signals,
    trades,
    lessons,
    intent,
    regime,
    logs,
    llmSummary,
    llmBreakdown,
    newsSentiment,
    strategyDiagnostics,
    rlCostSummary,
    rlWeights,
    rlTuning,
  };
}

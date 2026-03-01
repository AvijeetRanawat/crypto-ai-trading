import { useCallback, useEffect, useRef, useState } from "react";
import { dashboardApi } from "../services/dashboardApi";
import {
  DEFAULT_INTENT,
  DEFAULT_LLM_SUMMARY,
  DEFAULT_REGIME,
  DEFAULT_SUMMARY,
  DEFAULT_WARMUP,
  type IntentData,
  type Lesson,
  type LlmSummary,
  type MarketPoint,
  type PortfolioSummary,
  type RegimeData,
  type SignalEvent,
  type Trade,
  type WarmupData,
} from "../types/dashboard";
import { STORAGE_KEYS } from "../utils/constants";

interface DashboardDataState {
  nowMs: number;
  startTimeMs: number;
  warmup: WarmupData;
  marketHistory: MarketPoint[];
  summary: PortfolioSummary;
  signals: SignalEvent[];
  trades: Trade[];
  lessons: Lesson[];
  intent: IntentData;
  regime: RegimeData;
  logs: string;
  llmSummary: LlmSummary;
}

const FAST_POLL_MS = 3000;
const SLOW_POLL_MS = 8000;

export function useDashboardData(symbol = "BTCUSDT"): DashboardDataState {
  const [nowMs, setNowMs] = useState(Date.now());
  const [startTimeMs, setStartTimeMs] = useState<number>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.sessionStartMs);
    return stored ? Number(stored) : Date.now();
  });

  const [warmup, setWarmup] = useState<WarmupData>(DEFAULT_WARMUP);
  const [marketHistory, setMarketHistory] = useState<MarketPoint[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary>(DEFAULT_SUMMARY);
  const [signals, setSignals] = useState<SignalEvent[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [intent, setIntent] = useState<IntentData>(DEFAULT_INTENT);
  const [regime, setRegime] = useState<RegimeData>(DEFAULT_REGIME);
  const [logs, setLogs] = useState("...");
  const [llmSummary, setLlmSummary] = useState<LlmSummary>(DEFAULT_LLM_SUMMARY);

  const sessionStartRef = useRef<string | null>(localStorage.getItem(STORAGE_KEYS.sessionStart));

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
  }, []);

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
      await syncSessionStart();
      if (!active) return;

      const [warm, market, portfolio, currentIntent, signalData, regimeData] = await Promise.all([
        dashboardApi.warmup(),
        dashboardApi.marketHistory(symbol),
        dashboardApi.portfolioSummary(),
        dashboardApi.intent(),
        dashboardApi.signals(symbol, 60),
        dashboardApi.regime(),
      ]);

      if (!active) return;
      if (warm) setWarmup(warm);
      if (market) setMarketHistory(market);
      if (portfolio) setSummary(portfolio);
      if (currentIntent) setIntent(currentIntent);
      if (signalData) setSignals(signalData);
      if (regimeData) setRegime(regimeData);
    };

    const slowPoll = async () => {
      const [tradeData, lessonData, logData, usage] = await Promise.all([
        dashboardApi.tradesRecent(),
        dashboardApi.lessons(),
        dashboardApi.logs(60),
        dashboardApi.llmSummary(),
      ]);

      if (!active) return;
      if (tradeData) setTrades(tradeData);
      if (lessonData) setLessons(lessonData);
      if (logData?.logs) setLogs(logData.logs.join("").trim());
      if (usage) setLlmSummary(usage);
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
  }, [symbol, syncSessionStart]);

  return {
    nowMs,
    startTimeMs,
    warmup,
    marketHistory,
    summary,
    signals,
    trades,
    lessons,
    intent,
    regime,
    logs,
    llmSummary,
  };
}

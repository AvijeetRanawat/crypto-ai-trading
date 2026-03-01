import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../../App";
import {
  DEFAULT_INTENT,
  DEFAULT_LLM_BREAKDOWN,
  DEFAULT_LLM_SUMMARY,
  DEFAULT_NEWS_SENTIMENT,
  DEFAULT_RL_COST_SUMMARY,
  DEFAULT_RL_TUNING,
  DEFAULT_RL_WEIGHTS,
  DEFAULT_REGIME,
  DEFAULT_STRATEGY_DIAGNOSTICS,
  DEFAULT_SUMMARY,
  DEFAULT_WARMUP,
} from "../../types/dashboard";

vi.mock("../../components/LeftPanel", () => ({
  LeftPanel: ({ selectedSymbol }: { selectedSymbol: string }) => <div>LeftPanel:{selectedSymbol}</div>,
}));

vi.mock("../../components/LogsPanel", () => ({
  LogsPanel: ({ logs }: { logs: string }) => <div>LogsPanel:{logs}</div>,
}));

vi.mock("../../hooks/useDashboardData", () => ({
  useDashboardData: () => ({
    nowMs: Date.now(),
    startTimeMs: Date.now() - 10000,
    warmup: { ...DEFAULT_WARMUP, done: true },
    marketHistory: [],
    summary: { ...DEFAULT_SUMMARY, total_trades: 2, win_rate: 50 },
    signals: [],
    trades: [],
    lessons: [],
    intent: DEFAULT_INTENT,
    regime: DEFAULT_REGIME,
    logs: "ok",
    llmSummary: DEFAULT_LLM_SUMMARY,
    llmBreakdown: DEFAULT_LLM_BREAKDOWN,
    newsSentiment: DEFAULT_NEWS_SENTIMENT,
    strategyDiagnostics: DEFAULT_STRATEGY_DIAGNOSTICS,
    rlCostSummary: DEFAULT_RL_COST_SUMMARY,
    rlWeights: DEFAULT_RL_WEIGHTS,
    rlTuning: DEFAULT_RL_TUNING,
  }),
}));

describe("App smoke", () => {
  it("renders shell and supports mode switch", () => {
    render(<App />);

    expect(screen.getByText(/AI Trading Terminal/i)).toBeInTheDocument();
    expect(screen.getByText(/LeftPanel:/i)).toBeInTheDocument();
    expect(screen.getByText(/LogsPanel:/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "FUTURES" }));
    expect(screen.getByText(/SIMULATION · FUTURES/i)).toBeInTheDocument();
  });
});

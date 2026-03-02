import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RightPanel } from "../../components/RightPanel";
import { TopBar } from "../../components/TopBar";
import {
  DEFAULT_INTENT,
  DEFAULT_LLM_BREAKDOWN,
  DEFAULT_LLM_SUMMARY,
  DEFAULT_NEWS_SENTIMENT,
  DEFAULT_REGIME,
  DEFAULT_STRATEGY_DIAGNOSTICS,
} from "../../types/dashboard";

describe("TopBar integration", () => {
  it("toggles theme and changes trading mode", () => {
    const onToggleTheme = vi.fn();
    const onTradingModeChange = vi.fn();

    render(
      <TopBar
        theme="dark"
        onToggleTheme={onToggleTheme}
        tradingMode="SPOT"
        onTradingModeChange={onTradingModeChange}
        summary={{
          total_pnl: 10,
          win_rate: 55,
          total_trades: 20,
          missed_count: 1,
          traded_signals: 10,
          llm_cost_today: 1.2,
          llm_calls_today: 5,
          llm_cost_session: 0.4,
          llm_calls_session: 2,
          llm_tokens_session: 123,
          llm_decision_calls_session: 2,
          llm_cost_per_traded_signal: 0.04,
          llm_cost_per_dollar_pnl: 0.1,
          llm_trade_conversion_rate: 50,
          open_positions: [],
        }}
        balance={1260}
        uptime="00:10:00"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(onToggleTheme).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "FUTURES" }));
    expect(onTradingModeChange).toHaveBeenCalledWith("FUTURES");
  });
});

describe("RightPanel integration", () => {
  it("opens both detail modals from expand buttons", () => {
    render(
      <RightPanel
        panelWidth={480}
        regime={{ ...DEFAULT_REGIME, regime: "BULL", verdict: "Bull trend" }}
        intent={{ ...DEFAULT_INTENT, message: "Scanning..." }}
        latestSignal={null}
        llmSummary={DEFAULT_LLM_SUMMARY}
        llmBreakdown={{
          ...DEFAULT_LLM_BREAKDOWN,
          all_time: [
            {
              model_id: "gpt-4o",
              calls: 3,
              total_tokens: 1000,
              input_tokens: 800,
              output_tokens: 200,
              cost_usd: 0.05,
            },
          ],
        }}
        newsSentiment={{
          ...DEFAULT_NEWS_SENTIMENT,
          symbol: "BTCUSDT",
          sentiment_label: "BULLISH",
          sentiment_score: 0.42,
          components: {
            ...DEFAULT_NEWS_SENTIMENT.components,
            articles_count: 1,
            sources_available: { cointelegraph: true },
          },
          articles: [
            {
              source: "Cointelegraph",
              title: "BTC breaks key resistance",
              url: "https://example.com/btc",
              published_at: "2026-03-01T00:00:00Z",
              sentiment_score: 0.4,
            },
          ],
        }}
        strategyDiagnostics={DEFAULT_STRATEGY_DIAGNOSTICS}
        lessons={[]}
      />,
    );

    const expandButtons = screen.getAllByRole("button", { name: /expand/i });
    fireEvent.click(expandButtons[0]);
    expect(screen.getByText(/Market Sentiment & News Breakdown/i)).toBeInTheDocument();

    fireEvent.click(expandButtons[1]);
    expect(screen.getByText(/Model-wise Breakdown \(All-Time\)/i)).toBeInTheDocument();
  });
});

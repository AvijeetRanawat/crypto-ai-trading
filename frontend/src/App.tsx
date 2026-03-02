import { useEffect, useMemo, useState } from "react";
import { LeftPanel } from "./components/LeftPanel";
import { LogsPanel } from "./components/LogsPanel";
import { RightPanel } from "./components/RightPanel";
import { TopBar } from "./components/TopBar";
import { useDashboardData } from "./hooks/useDashboardData";
import { useResizableLogs } from "./hooks/useResizableLogs";
import { useResizablePanel } from "./hooks/useResizablePanel";
import { useTheme } from "./hooks/useTheme";
import { formatUptime } from "./utils/format";
import { STARTING_BALANCE, STORAGE_KEYS, SYMBOLS_BY_TRADING_MODE, TRADING_MODES, type TradingMode } from "./utils/constants";

function App() {
  const [tradingMode, setTradingMode] = useState<TradingMode>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.tradingMode);
    if (stored && (TRADING_MODES as readonly string[]).includes(stored)) {
      return stored as TradingMode;
    }
    return "SPOT";
  });
  const symbolOptions = useMemo(() => [...SYMBOLS_BY_TRADING_MODE[tradingMode]], [tradingMode]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>(() => symbolOptions[0] || "BTCUSDT");
  const [theme, setTheme] = useTheme();
  const {
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
    llmBreakdown,
    newsSentiment,
    strategyDiagnostics,
    rlCostSummary,
    rlWeights,
    rlTuning,
  } = useDashboardData(selectedSymbol, tradingMode);

  const { panelWidth, onResizeMouseDown } = useResizablePanel();
  const { logsHeight, onResizeMouseDown: onLogsResizeMouseDown } = useResizableLogs();

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.tradingMode, tradingMode);
  }, [tradingMode]);

  useEffect(() => {
    if (!symbolOptions.includes(selectedSymbol)) {
      setSelectedSymbol(symbolOptions[0] || "BTCUSDT");
    }
  }, [symbolOptions, selectedSymbol]);

  const balance = useMemo(() => STARTING_BALANCE + Number(summary.total_pnl || 0), [summary.total_pnl]);
  const uptime = useMemo(() => formatUptime(startTimeMs, nowMs), [startTimeMs, nowMs]);
  const latestSignal = useMemo(() => (signals.length ? signals[signals.length - 1] : null), [signals]);

  return (
    <div className="app">
      <TopBar
        theme={theme}
        onToggleTheme={() => setTheme(theme === "light" ? "dark" : "light")}
        tradingMode={tradingMode}
        onTradingModeChange={setTradingMode}
        summary={summary}
        balance={balance}
        uptime={uptime}
      />

      <main className="dashboard">
        <LeftPanel
          theme={theme}
          selectedSymbol={selectedSymbol}
          symbolOptions={symbolOptions}
          onSelectSymbol={setSelectedSymbol}
          warmup={warmup}
          marketHistory={marketHistory}
          summary={summary}
          signals={signals}
          trades={trades}
          rlCostSummary={rlCostSummary}
          rlWeights={rlWeights}
          rlTuning={rlTuning}
          tradingMode={tradingMode}
        />

        <div id="v-resizer" className="resizer-v" onMouseDown={onResizeMouseDown} />

        <RightPanel
          panelWidth={panelWidth}
          regime={regime}
          intent={intent}
          latestSignal={latestSignal}
          llmSummary={llmSummary}
          llmBreakdown={llmBreakdown}
          newsSentiment={newsSentiment}
          strategyDiagnostics={strategyDiagnostics}
          lessons={lessons}
        />
      </main>

      <div id="h-resizer" className="resizer-h" onMouseDown={onLogsResizeMouseDown} />
      <LogsPanel logs={logs} height={logsHeight} />
    </div>
  );
}

export default App;

import { useMemo, useState } from "react";
import { LeftPanel } from "./components/LeftPanel";
import { LogsPanel } from "./components/LogsPanel";
import { RightPanel } from "./components/RightPanel";
import { TopBar } from "./components/TopBar";
import { useDashboardData } from "./hooks/useDashboardData";
import { useResizableLogs } from "./hooks/useResizableLogs";
import { useResizablePanel } from "./hooks/useResizablePanel";
import { useTheme } from "./hooks/useTheme";
import { formatUptime } from "./utils/format";
import { SUPPORTED_SYMBOLS } from "./utils/constants";

function App() {
  const [selectedSymbol, setSelectedSymbol] = useState<string>(SUPPORTED_SYMBOLS[0]);
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
  } = useDashboardData(selectedSymbol);

  const { panelWidth, onResizeMouseDown } = useResizablePanel();
  const { logsHeight, onResizeMouseDown: onLogsResizeMouseDown } = useResizableLogs();

  const balance = useMemo(() => 1250 + Number(summary.total_pnl || 0), [summary.total_pnl]);
  const uptime = useMemo(() => formatUptime(startTimeMs, nowMs), [startTimeMs, nowMs]);
  const latestSignal = useMemo(() => (signals.length ? signals[signals.length - 1] : null), [signals]);

  return (
    <div className="app">
      <TopBar
        theme={theme}
        onToggleTheme={() => setTheme(theme === "light" ? "dark" : "light")}
        summary={summary}
        balance={balance}
        uptime={uptime}
      />

      <main className="dashboard">
        <LeftPanel
          theme={theme}
          selectedSymbol={selectedSymbol}
          onSelectSymbol={setSelectedSymbol}
          warmup={warmup}
          marketHistory={marketHistory}
          summary={summary}
          signals={signals}
          trades={trades}
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
          lessons={lessons}
        />
      </main>

      <div id="h-resizer" className="resizer-h" onMouseDown={onLogsResizeMouseDown} />
      <LogsPanel logs={logs} height={logsHeight} />
    </div>
  );
}

export default App;

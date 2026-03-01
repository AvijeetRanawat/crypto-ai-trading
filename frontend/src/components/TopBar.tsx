import type { PortfolioSummary } from "../types/dashboard";
import type { ThemeMode } from "../hooks/useTheme";
import { formatUsd } from "../utils/format";

interface TopBarProps {
  theme: ThemeMode;
  onToggleTheme: () => void;
  summary: PortfolioSummary;
  balance: number;
  uptime: string;
}

export function TopBar({ theme, onToggleTheme, summary, balance, uptime }: TopBarProps) {
  const pnlClass = summary.total_pnl >= 0 ? "positive" : "negative";

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="dot-live" />
        <span className="brand-name">AI Trading Terminal</span>
        <span className="mode-badge">SIMULATION · React TS</span>
      </div>
      <div className="topbar-right">
        <button
          id="theme-toggle"
          className="theme-toggle"
          type="button"
          aria-label="Toggle theme"
          onClick={onToggleTheme}
        >
          {theme === "light" ? "Dark" : "Light"}
        </button>

        <div className="stat-pill">
          <span className="pill-label">BALANCE</span>
          <span className="pill-value">
            ${balance.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">P/L</span>
          <span className={`pill-value ${pnlClass}`}>{formatUsd(summary.total_pnl)}</span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">WIN RATE</span>
          <span className="pill-value">
            {summary.total_trades > 0 ? `${summary.win_rate.toFixed(1)}%` : "--%"}
          </span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">TRADES</span>
          <span className="pill-value mono">{summary.total_trades}</span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">MISSED</span>
          <span className="pill-value mono" style={{ color: "var(--yellow)" }}>
            {summary.missed_count}
          </span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">LLM $/DAY</span>
          <span className="pill-value mono">${summary.llm_cost_today.toFixed(4)}</span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">LLM $/TRADE</span>
          <span className="pill-value mono">
            {summary.llm_cost_per_traded_signal != null
              ? `$${summary.llm_cost_per_traded_signal.toFixed(4)}`
              : "-"}
          </span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">LLM $/$PNL</span>
          <span className="pill-value mono">
            {summary.llm_cost_per_dollar_pnl != null
              ? `${summary.llm_cost_per_dollar_pnl.toFixed(4)}x`
              : "-"}
          </span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">LLM CONV</span>
          <span className="pill-value mono">{summary.llm_trade_conversion_rate.toFixed(1)}%</span>
        </div>

        <div className="stat-pill">
          <span className="pill-label">UPTIME</span>
          <span className="pill-value mono">{uptime}</span>
        </div>
      </div>
    </header>
  );
}

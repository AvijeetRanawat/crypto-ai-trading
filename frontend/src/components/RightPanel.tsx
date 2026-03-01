import type { IntentData, Lesson, LlmSummary, RegimeData, SignalEvent } from "../types/dashboard";
import { formatNum } from "../utils/format";
import { TOTAL_VOTES } from "../utils/constants";

interface RightPanelProps {
  panelWidth: number;
  regime: RegimeData;
  intent: IntentData;
  latestSignal: SignalEvent | null;
  llmSummary: LlmSummary;
  lessons: Lesson[];
}

function regimeClassName(regime: string): string {
  if (regime === "BULL") return "regime-bull";
  if (regime === "BEAR") return "regime-bear";
  if (regime === "CHOPPY") return "regime-choppy";
  return "regime-neutral";
}

function sessionClassName(quality: string): string {
  if (quality === "PREMIUM") return "sess-premium";
  if (quality === "HIGH") return "sess-high";
  if (quality === "MODERATE") return "sess-moderate";
  return "sess-low";
}

export function RightPanel({ panelWidth, regime, intent, latestSignal, llmSummary, lessons }: RightPanelProps) {
  const buyVotes = latestSignal?.buy_votes ?? 0;
  const sellVotes = latestSignal?.sell_votes ?? 0;

  return (
    <aside className="ai-panel" style={{ width: `${panelWidth}px` }}>
      <div className="panel-section glass">
        <div className="section-header">
          <span>MARKET REGIME</span>
        </div>
        <div className="regime-row">
          <span className={`regime-badge ${regimeClassName(regime.regime)}`}>{regime.regime || "WARMING_UP"}</span>
          <div className="regime-detail">
            <div className="regime-verdict-text">{regime.verdict || "Loading..."}</div>
            <div className="atr-text">{regime.atr_verdict || "ATR: -"}</div>
          </div>
        </div>
        <div className="session-row">
          <span className={`sess-badge ${sessionClassName(regime.session_quality)}`}>{regime.session || "-"}</span>
          <div className="sess-verdict-text">{regime.session_verdict || "Loading session window..."}</div>
        </div>
      </div>

      <div className="panel-section glass">
        <div className="section-header">
          <div className="pulse-dot" />
          <span>AI INTENT</span>
        </div>
        <div className="intent-text">{intent.message || "Initializing..."}</div>
      </div>

      <div className="panel-section glass signal-votes-panel">
        <div className="section-header">
          <span>LIVE VOTE TALLY</span>
        </div>
        <div className="vote-meters">
          <div className="vote-row">
            <span className="vote-label">BUY</span>
            <div className="vote-bar-wrap">
              <div
                className="vote-bar buy-bar"
                style={{ width: `${Math.min(100, (buyVotes / TOTAL_VOTES) * 100)}%` }}
              />
            </div>
            <span className="vote-count positive">{buyVotes}/{TOTAL_VOTES}</span>
          </div>
          <div className="vote-row">
            <span className="vote-label">SELL</span>
            <div className="vote-bar-wrap">
              <div
                className="vote-bar sell-bar"
                style={{ width: `${Math.min(100, (sellVotes / TOTAL_VOTES) * 100)}%` }}
              />
            </div>
            <span className="vote-count negative">{sellVotes}/{TOTAL_VOTES}</span>
          </div>
        </div>
        <div className="ta-grid">
          <div className="ta-cell">
            <div className="ta-name">RSI</div>
            <div className="ta-val">{latestSignal?.rsi != null ? latestSignal.rsi.toFixed(1) : "-"}</div>
          </div>
          <div className="ta-cell">
            <div className="ta-name">MACD</div>
            <div className="ta-val">{latestSignal?.macd || "-"}</div>
          </div>
          <div className="ta-cell">
            <div className="ta-name">BB%</div>
            <div className="ta-val">{latestSignal?.bb_pct != null ? `${latestSignal.bb_pct.toFixed(0)}%` : "-"}</div>
          </div>
          <div className="ta-cell">
            <div className="ta-name">Outcome</div>
            <div className={`ta-val ${latestSignal?.outcome === "TRADED" ? "positive" : latestSignal?.outcome === "MISSED" ? "warn" : "neutral"}`}>
              {latestSignal?.outcome || "-"}
            </div>
          </div>
        </div>
      </div>

      <div className="panel-section glass llm-usage-panel">
        <div className="section-header">
          <span>LLM TOKEN USAGE</span>
        </div>
        <div className="llm-usage-grid">
          <div className="llm-usage-row">
            <span className="llm-usage-label">Session</span>
            <span className="llm-usage-value mono">{formatNum(llmSummary.llm_tokens_session)}</span>
          </div>
          <div className="llm-usage-row">
            <span className="llm-usage-label">Today</span>
            <span className="llm-usage-value mono">{formatNum(llmSummary.llm_tokens_today)}</span>
          </div>
          <div className="llm-usage-row">
            <span className="llm-usage-label">All-Time</span>
            <span className="llm-usage-value mono">{formatNum(llmSummary.llm_tokens_all_time)}</span>
          </div>
          <div className="llm-usage-row">
            <span className="llm-usage-label">Calls (All-Time)</span>
            <span className="llm-usage-value mono">{formatNum(llmSummary.llm_calls_all_time)}</span>
          </div>
        </div>
      </div>

      <div className="panel-section glass lessons-panel">
        <div className="section-header">
          <span>LESSONS LEARNED</span>
        </div>
        <div className="lessons-list">
          {!lessons.length && <div className="empty-state">No lessons yet</div>}
          {lessons.map((lesson) => {
            const severity = lesson.severity.toUpperCase();
            const cls = severity === "GOLDEN" ? "lesson-gold" : severity === "WIN" ? "lesson-win" : "lesson-loss";
            return (
              <div className={`lesson-row ${cls}`} key={lesson.id || `${lesson.timestamp}-${lesson.condition}`}>
                <span className="lesson-text">
                  <b>{lesson.condition}</b> -&gt; {lesson.lesson}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

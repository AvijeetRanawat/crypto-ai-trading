import { useState } from "react";
import { LlmBreakdownModal } from "./LlmBreakdownModal";
import { MarketSentimentModal } from "./MarketSentimentModal";
import type {
  IntentData,
  Lesson,
  LlmBreakdown,
  LlmSummary,
  NewsSentiment,
  RegimeData,
  SignalEvent,
} from "../types/dashboard";
import { formatNum } from "../utils/format";
import { TOTAL_VOTES } from "../utils/constants";

interface RightPanelProps {
  panelWidth: number;
  regime: RegimeData;
  intent: IntentData;
  latestSignal: SignalEvent | null;
  llmSummary: LlmSummary;
  llmBreakdown: LlmBreakdown;
  newsSentiment: NewsSentiment;
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

function sentimentClassName(label: string): string {
  if (label === "BULLISH") return "sentiment-bull";
  if (label === "BEARISH") return "sentiment-bear";
  return "sentiment-neutral";
}

function articleSentimentLabel(score: number): "BULLISH" | "BEARISH" | "NEUTRAL" {
  if (score >= 0.2) return "BULLISH";
  if (score <= -0.2) return "BEARISH";
  return "NEUTRAL";
}

export function RightPanel({
  panelWidth,
  regime,
  intent,
  latestSignal,
  llmSummary,
  llmBreakdown,
  newsSentiment,
  lessons,
}: RightPanelProps) {
  const [llmExpanded, setLlmExpanded] = useState(false);
  const [sentimentExpanded, setSentimentExpanded] = useState(false);
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

      <div className="panel-section glass sentiment-panel">
        <div className="section-header llm-header">
          <span>MARKET SENTIMENT & NEWS</span>
          <button className="expand-btn" onClick={() => setSentimentExpanded(true)} type="button">
            Expand
          </button>
        </div>
        <div className="sentiment-summary-row">
          <span className={`sentiment-badge ${sentimentClassName(newsSentiment.sentiment_label)}`}>
            {newsSentiment.sentiment_label}
          </span>
          <span className="sentiment-score mono">{newsSentiment.sentiment_score.toFixed(2)}</span>
        </div>
        <div className="sentiment-meta">
          <span>Fear &amp; Greed: {newsSentiment.components.fear_greed.value ?? "-"}</span>
          <span>{newsSentiment.components.fear_greed.value_classification || "Unknown"}</span>
        </div>
        <div className="sentiment-meta">
          <span>News Items: {newsSentiment.components.articles_count}</span>
          <span>Updated: {newsSentiment.updated_at ? "live" : "-"}</span>
        </div>
        <div className="llm-summary-box">
          <div className="llm-summary-head">
            <span>GPT Summary</span>
            <span className="mono">{newsSentiment.llm_summary?.model_id || "gpt-5-nano"}</span>
          </div>
          <div className="llm-summary-text">
            {newsSentiment.llm_summary?.text || "Summary pending..."}
          </div>
        </div>
        <div className="sentiment-subsection-title">Latest News + Sentiment</div>
        <div className="news-list">
          {!newsSentiment.articles.length && <div className="empty-state">No news data yet</div>}
          {newsSentiment.articles.slice(0, 5).map((item) => {
            const label = articleSentimentLabel(item.sentiment_score);
            return (
              <a
                className="news-item"
                href={item.url || "#"}
                key={`${item.source}-${item.url}-${item.title}`}
                rel="noreferrer"
                target="_blank"
              >
                <span className="news-source">
                  {item.source}
                  {" · "}
                  <span className={`news-sentiment-tag ${sentimentClassName(label)}`}>
                    {label} ({item.sentiment_score.toFixed(2)})
                  </span>
                </span>
                <span className="news-title">{item.title}</span>
              </a>
            );
          })}
        </div>
      </div>

      <div className="panel-section glass llm-usage-panel">
        <div className="section-header llm-header">
          <span>LLM TOKEN USAGE</span>
          <button className="expand-btn" onClick={() => setLlmExpanded((v) => !v)} type="button">
            {llmExpanded ? "Collapse" : "Expand"}
          </button>
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
      <LlmBreakdownModal
        open={llmExpanded}
        models={llmBreakdown.all_time}
        onClose={() => setLlmExpanded(false)}
      />
      <MarketSentimentModal
        open={sentimentExpanded}
        sentiment={newsSentiment}
        onClose={() => setSentimentExpanded(false)}
      />

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

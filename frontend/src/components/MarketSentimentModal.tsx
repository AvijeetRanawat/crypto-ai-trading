import type { NewsSentiment } from "../types/dashboard";

interface MarketSentimentModalProps {
  open: boolean;
  sentiment: NewsSentiment;
  decision: "BUY" | "SELL" | "SKIP";
  onClose: () => void;
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

function decisionClassName(decision: "BUY" | "SELL" | "SKIP"): string {
  if (decision === "BUY") return "sentiment-bull";
  if (decision === "SELL") return "sentiment-bear";
  return "sentiment-neutral";
}

export function MarketSentimentModal({ open, sentiment, decision, onClose }: MarketSentimentModalProps) {
  if (!open) return null;

  const sources = sentiment.components.sources_available || {};

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="llm-modal glass" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="llm-modal-header">
          <div className="llm-breakdown-title">Market Sentiment & News Breakdown</div>
          <button className="modal-close-btn" onClick={onClose} type="button" aria-label="Close modal">
            &times;
          </button>
        </div>

        <div className="sentiment-modal-stats">
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Weighted Decision</span>
            <span className={`sentiment-badge ${decisionClassName(decision)}`}>{decision}</span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Symbol</span>
            <span className="mono">{sentiment.symbol || "-"}</span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Composite</span>
            <span className={`sentiment-badge ${sentimentClassName(sentiment.sentiment_label)}`}>
              {sentiment.sentiment_label} ({sentiment.sentiment_score.toFixed(2)})
            </span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">News Score</span>
            <span className="mono">{sentiment.components.news_score.toFixed(2)}</span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Fear &amp; Greed</span>
            <span className="mono">
              {(sentiment.components.fear_greed.value ?? "-")}
              {" "}
              ({sentiment.components.fear_greed.value_classification || "Unknown"})
            </span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Articles</span>
            <span className="mono">{sentiment.components.articles_count}</span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Updated</span>
            <span className="mono">{sentiment.updated_at || "-"}</span>
          </div>
        </div>

        <div className="sentiment-source-row">
          {Object.keys(sources).length === 0 && <span className="empty-state">No source info</span>}
          {Object.entries(sources).map(([source, ok]) => (
            <span className={`sentiment-source-pill ${ok ? "ok" : "down"}`} key={source}>
              {source}: {ok ? "up" : "down"}
            </span>
          ))}
        </div>

        <div className="llm-breakdown-wrap llm-breakdown-modal-body sentiment-modal-list">
          {!sentiment.articles.length && <div className="empty-state">No articles yet</div>}
          {sentiment.articles.map((item) => {
            const label = articleSentimentLabel(item.sentiment_score);
            return (
              <a
                className="news-item sentiment-modal-item"
                href={item.url || "#"}
                key={`${item.source}-${item.url}-${item.title}`}
                rel="noreferrer"
                target="_blank"
              >
                <div className="sentiment-modal-item-head">
                  <span className="news-source">{item.source}</span>
                  <span className={`sentiment-mini-badge ${sentimentClassName(label)}`}>
                    {label} ({item.sentiment_score.toFixed(2)})
                  </span>
                </div>
                <span className="news-title">{item.title}</span>
                <span className="sentiment-modal-time mono">{item.published_at || "-"}</span>
              </a>
            );
          })}
        </div>
      </div>
    </div>
  );
}

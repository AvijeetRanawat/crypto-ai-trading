import type { LlmModelUsage } from "../types/dashboard";
import { formatNum } from "../utils/format";

interface LlmBreakdownModalProps {
  open: boolean;
  models: LlmModelUsage[];
  onClose: () => void;
}

export function LlmBreakdownModal({ open, models, onClose }: LlmBreakdownModalProps) {
  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="llm-modal glass" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="llm-modal-header">
          <div className="llm-breakdown-title">Model-wise Breakdown (All-Time)</div>
          <button className="modal-close-btn" onClick={onClose} type="button" aria-label="Close modal">
            &times;
          </button>
        </div>
        <div className="llm-breakdown-wrap llm-breakdown-modal-body">
          {!models.length && <div className="empty-state">No LLM usage yet</div>}
          {models.map((m) => (
            <div className="llm-breakdown-row" key={`llm-model-${m.model_id}`}>
              <div className="llm-breakdown-model mono">{m.model_id}</div>
              <div className="llm-breakdown-metrics">
                <span>Tok: {formatNum(m.total_tokens)}</span>
                <span>In: {formatNum(m.input_tokens)}</span>
                <span>Out: {formatNum(m.output_tokens)}</span>
                <span>Calls: {formatNum(m.calls)}</span>
                <span>Cost: ${m.cost_usd.toFixed(4)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

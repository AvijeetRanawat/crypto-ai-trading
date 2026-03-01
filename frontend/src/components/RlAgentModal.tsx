import { useMemo, useState } from "react";
import type { RlLearnedState, RlWeightsSnapshot } from "../types/dashboard";

interface RlAgentModalProps {
  open: boolean;
  mode: string;
  weights: RlWeightsSnapshot;
  onClose: () => void;
}

function formatMult(value: number | undefined): string {
  if (value == null) return "-";
  return value.toFixed(2);
}

function stateRowsForMode(weights: RlWeightsSnapshot, mode: string): RlLearnedState[] {
  const rows = weights.learned?.[mode] || [];
  return rows.slice(0, 16);
}

export function RlAgentModal({ open, mode, weights, onClose }: RlAgentModalProps) {
  if (!open) return null;

  const initialMode = useMemo(() => {
    const normalized = String(mode || "SPOT").toUpperCase();
    return normalized === "FUTURES" || normalized === "OPTIONS" ? normalized : "SPOT";
  }, [mode]);
  const [activeMode, setActiveMode] = useState<string>(initialMode);
  const modeRows = stateRowsForMode(weights, activeMode);
  const modeProfiles = weights.profiles?.[activeMode] || {};

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="llm-modal glass" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="llm-modal-header">
          <div className="llm-breakdown-title">RL Agent Weights</div>
          <button className="modal-close-btn" onClick={onClose} type="button" aria-label="Close modal">
            &times;
          </button>
        </div>

        <div className="sentiment-modal-stats">
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Mode</span>
            <span className="mono">{activeMode}</span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Epsilon</span>
            <span className="mono">{Number(weights.meta?.epsilon || 0).toFixed(4)}</span>
          </div>
          <div className="sentiment-modal-stat">
            <span className="sentiment-modal-key">Updated</span>
            <span className="mono">{weights.meta?.updated_at || "-"}</span>
          </div>
        </div>

        <div className="rl-tabs">
          {["SPOT", "FUTURES", "OPTIONS"].map((tab) => (
            <button
              className={`rl-tab-btn ${activeMode === tab ? "active" : ""}`}
              key={tab}
              onClick={() => setActiveMode(tab)}
              type="button"
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="sentiment-subsection-title">Profile Multipliers</div>
        <div className="rl-profile-grid">
          {!Object.keys(modeProfiles).length && <div className="empty-state">No profile data</div>}
          {Object.entries(modeProfiles).map(([profileId, profile]) => (
            <div className="rl-profile-card" key={profileId}>
              <div className="rl-profile-title mono">{profileId}</div>
              <div className="rl-profile-row">
                <span>Size</span>
                <span className="mono">{formatMult(profile.size_mult)}</span>
              </div>
              <div className="rl-profile-row">
                <span>Leverage</span>
                <span className="mono">{formatMult(profile.leverage_mult)}</span>
              </div>
              <div className="rl-profile-row">
                <span>Confidence Bias</span>
                <span className="mono">{formatMult(profile.confidence_bias)}</span>
              </div>
              <div className="rl-profile-row">
                <span>Sentiment Gate</span>
                <span className="mono">{formatMult(profile.sentiment_gate_mult)}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="sentiment-subsection-title">Learned State Q/N</div>
        <div className="llm-breakdown-wrap llm-breakdown-modal-body rl-learned-list">
          {!modeRows.length && <div className="empty-state">No learned state rows yet</div>}
          {modeRows.map((row) => (
            <div className="rl-learned-item" key={row.state_key}>
              <div className="rl-learned-head">
                <span className="mono rl-state-key">{row.state_key}</span>
                <span className="mono">n={row.total_n}</span>
              </div>
              <div className="rl-learned-profiles">
                {row.profiles.map((profile) => (
                  <span className="rl-learned-pill mono" key={`${row.state_key}-${profile.profile_id}`}>
                    {profile.profile_id}: q={profile.q.toFixed(5)} | n={profile.n}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

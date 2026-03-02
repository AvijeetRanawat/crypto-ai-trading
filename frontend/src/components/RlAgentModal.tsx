import { useEffect, useMemo, useState } from "react";
import { dashboardApi } from "../services/dashboardApi";
import type { RlLearnedState, RlTuningSnapshot, RlWeightsSnapshot } from "../types/dashboard";

interface RlAgentModalProps {
  open: boolean;
  mode: string;
  weights: RlWeightsSnapshot;
  tuning: RlTuningSnapshot;
  onClose: () => void;
}

function formatMult(value: number | undefined): string {
  if (value == null) return "-";
  return value.toFixed(2);
}

function renderMultiplierMap(map: Record<string, number> | undefined) {
  const entries = Object.entries(map || {});
  if (!entries.length) {
    return <span className="rl-map-empty mono">-</span>;
  }
  return (
    <div className="rl-map-grid">
      {entries.map(([key, value]) => (
        <span className="rl-map-pill mono" key={key}>
          {key}:{Number(value).toFixed(2)}
        </span>
      ))}
    </div>
  );
}

function stateRowsForMode(weights: RlWeightsSnapshot, mode: string): RlLearnedState[] {
  const rows = weights.learned?.[mode] || [];
  return rows.slice(0, 16);
}

export function RlAgentModal({ open, mode, weights, tuning, onClose }: RlAgentModalProps) {
  const initialMode = useMemo(() => {
    const normalized = String(mode || "SPOT").toUpperCase();
    return normalized === "FUTURES" || normalized === "OPTIONS" ? normalized : "SPOT";
  }, [mode]);
  const [activeMode, setActiveMode] = useState<string>(initialMode);
  const [draft, setDraft] = useState<Record<string, number | boolean | null>>({});
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState("");
  const [isDirty, setIsDirty] = useState(false);
  const modeRows = stateRowsForMode(weights, activeMode);
  const modeProfiles = weights.profiles?.[activeMode] || {};
  const tunableSettings = useMemo(() => (tuning.settings || []), [tuning.settings]);

  // Sync activeMode when parent mode changes
  useEffect(() => {
    setActiveMode(initialMode);
  }, [initialMode]);

  useEffect(() => {
    // Only sync draft from server when user hasn't made local edits
    if (isDirty) return;
    const next: Record<string, number | boolean | null> = {};
    for (const item of tuning.settings || []) {
      next[item.key] = item.value as number | boolean;
    }
    setDraft(next);
  }, [tuning, isDirty]);

  if (!open) return null;

  const onSave = async () => {
    setSaving(true);
    setSaveStatus("");
    const updated = await dashboardApi.updateRlTuning(draft);
    setSaving(false);
    if (!updated || (updated as { error?: string }).error) {
      setSaveStatus("Save failed");
      return;
    }
    setSaveStatus("Saved");
    setIsDirty(false);
  };

  const onReset = async () => {
    if (!tunableSettings.length) return;
    const resetValues: Record<string, null> = {};
    for (const item of tunableSettings) resetValues[item.key] = null;
    setSaving(true);
    setSaveStatus("");
    const updated = await dashboardApi.updateRlTuning(resetValues);
    setSaving(false);
    if (!updated || (updated as { error?: string }).error) {
      setSaveStatus("Reset failed");
      return;
    }
    setSaveStatus("Reset to defaults");
    setIsDirty(false);
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="llm-modal glass" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="llm-modal-header">
          <div className="llm-breakdown-title">RL Agent Weights</div>
          <button className="modal-close-btn" onClick={onClose} type="button" aria-label="Close modal">
            &times;
          </button>
        </div>

        <div className="llm-modal-scroll">
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
                <div className="rl-profile-map">
                  <span className="rl-profile-map-title">Voter Multipliers</span>
                  {renderMultiplierMap(profile.voter_weight_mult)}
                </div>
                <div className="rl-profile-map">
                  <span className="rl-profile-map-title">Strategy Multipliers</span>
                  {renderMultiplierMap(profile.weight_mult)}
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

          <div className="sentiment-subsection-title">Runtime RL Tuning</div>
          <div className="llm-breakdown-wrap llm-breakdown-modal-body rl-learned-list">
            {!tunableSettings.length && <div className="empty-state">No tunable settings found</div>}
            {!!tunableSettings.length &&
              tunableSettings.map((setting) => {
                const val = draft[setting.key];
                return (
                  <div className="rl-learned-item" key={setting.key}>
                    <div className="rl-learned-head">
                      <span className="mono rl-state-key">{setting.key}</span>
                      <span className="mono">{setting.overridden ? "override" : "default"}</span>
                    </div>
                    <div className="rl-profile-row">
                      <span>Current</span>
                      <span className="mono">{String(setting.value)}</span>
                    </div>
                    <div className="rl-profile-row">
                      <span>Default</span>
                      <span className="mono">{String(setting.default)}</span>
                    </div>
                    {setting.type === "bool" ? (
                      <label className="rl-profile-row" htmlFor={setting.key}>
                        <span>Value</span>
                        <input
                          id={setting.key}
                          type="checkbox"
                          checked={Boolean(val)}
                          onChange={(e) => {
                            setIsDirty(true);
                            setDraft((prev) => ({
                              ...prev,
                              [setting.key]: e.target.checked,
                            }));
                          }}
                        />
                      </label>
                    ) : (
                      <label className="rl-profile-row" htmlFor={setting.key}>
                        <span>Value</span>
                        <input
                          id={setting.key}
                          className="rl-tune-input mono"
                          type="number"
                          step={setting.type === "int" ? 1 : 0.0001}
                          min={setting.min}
                          max={setting.max}
                          value={typeof val === "number" ? val : Number(setting.value)}
                          onChange={(e) => {
                            setIsDirty(true);
                            setDraft((prev) => ({
                              ...prev,
                              [setting.key]:
                                setting.type === "int"
                                  ? Number.parseInt(e.target.value || "0", 10)
                                  : Number.parseFloat(e.target.value || "0"),
                            }));
                          }}
                        />
                      </label>
                    )}
                  </div>
                );
              })}
            <div className="rl-modal-actions">
              <button className="expand-btn" onClick={onSave} disabled={saving} type="button">
                {saving ? "Saving..." : "Save Tuning"}
              </button>
              <button className="expand-btn" onClick={onReset} disabled={saving} type="button">
                Reset Defaults
              </button>
              <span className="mono">{saveStatus}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

import type { PortfolioBalances } from "../types/dashboard";
import { formatUsd } from "../utils/format";

interface CryptoBalancesModalProps {
  open: boolean;
  onClose: () => void;
  balances: PortfolioBalances | null;
}

export function CryptoBalancesModal({ open, onClose, balances }: CryptoBalancesModalProps) {
  if (!open || !balances) return null;

  const totalPnlClass = balances.total_unrealized_pnl >= 0 ? "positive" : "negative";

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="llm-modal glass" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="llm-modal-header">
          <div className="llm-breakdown-title">Crypto Holdings</div>
          <button className="modal-close-btn" onClick={onClose} type="button" aria-label="Close modal">
            &times;
          </button>
        </div>

        <div className="llm-modal-scroll">
          <div className="balances-summary-header">
            <div className="summary-stat">
              <span className="summary-label">Total Cost Basis</span>
              <span className="summary-value">{formatUsd(balances.total_cost_basis)}</span>
            </div>
            <div className="summary-stat">
              <span className="summary-label">Total Current Value</span>
              <span className="summary-value">{formatUsd(balances.total_current_value)}</span>
            </div>
            <div className="summary-stat">
              <span className="summary-label">Total Unrealized P/L</span>
              <span className={`summary-value ${totalPnlClass}`}>
                {formatUsd(balances.total_unrealized_pnl)}
                {balances.total_cost_basis > 0 && (
                  <span className="summary-pct">
                    {" "}
                    ({balances.total_unrealized_pnl >= 0 ? "+" : ""}
                    {((balances.total_unrealized_pnl / balances.total_cost_basis) * 100).toFixed(2)}%)
                  </span>
                )}
              </span>
            </div>
          </div>

          <div className="balances-grid">
            {balances.balances.map((balance) => {
              const pnlClass = balance.unrealized_pnl >= 0 ? "positive" : "negative";
              const priceDigits = balance.current_price < 1 ? 6 : 2;

              return (
                <div key={balance.symbol} className="balance-card-detailed">
                  <div className="balance-header">
                    <span className="balance-symbol">{balance.symbol}</span>
                    <span className={`balance-pnl ${pnlClass}`}>
                      {formatUsd(balance.unrealized_pnl)} ({balance.unrealized_pnl >= 0 ? "+" : ""}
                      {balance.unrealized_pnl_pct.toFixed(2)}%)
                    </span>
                  </div>

                  <div className="balance-details">
                    <div className="balance-row">
                      <span className="balance-label">Quantity:</span>
                      <span className="balance-value mono">
                        {balance.total_quantity.toLocaleString("en-US", {
                          minimumFractionDigits: 6,
                          maximumFractionDigits: 8,
                        })}
                      </span>
                    </div>

                    <div className="balance-row">
                      <span className="balance-label">Avg Entry:</span>
                      <span className="balance-value mono">
                        $
                        {balance.avg_entry_price.toLocaleString("en-US", {
                          minimumFractionDigits: priceDigits,
                          maximumFractionDigits: priceDigits,
                        })}
                      </span>
                    </div>

                    <div className="balance-row">
                      <span className="balance-label">Current Price:</span>
                      <span className="balance-value mono">
                        $
                        {balance.current_price.toLocaleString("en-US", {
                          minimumFractionDigits: priceDigits,
                          maximumFractionDigits: priceDigits,
                        })}
                      </span>
                    </div>

                    <div className="balance-row">
                      <span className="balance-label">Cost Basis:</span>
                      <span className="balance-value mono">{formatUsd(balance.cost_basis)}</span>
                    </div>

                    <div className="balance-row">
                      <span className="balance-label">Current Value:</span>
                      <span className="balance-value mono">{formatUsd(balance.current_value)}</span>
                    </div>
                  </div>

                  {balance.positions.length > 1 && (
                    <div className="balance-positions-detail">
                      <div className="positions-header">{balance.positions.length} Positions:</div>
                      {balance.positions.map((pos) => (
                        <div key={pos.id} className="position-item">
                          <span className="position-side">{pos.side}</span>
                          <span className="position-pair mono">{pos.trading_pair}</span>
                          <span className="position-qty mono">
                            {pos.quantity.toLocaleString("en-US", {
                              minimumFractionDigits: 6,
                              maximumFractionDigits: 8,
                            })}
                          </span>
                          <span className="position-price mono">
                            @ {formatUsd(pos.entry_price)}
                          </span>
                          <span className={`position-pnl ${pos.unrealized_pnl >= 0 ? "positive" : "negative"}`}>
                            {formatUsd(pos.unrealized_pnl)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

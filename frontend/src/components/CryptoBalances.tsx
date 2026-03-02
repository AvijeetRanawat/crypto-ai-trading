import type { PortfolioBalances } from "../types/dashboard";
import { formatUsd } from "../utils/format";

interface CryptoBalancesProps {
  balances: PortfolioBalances | null;
}

export function CryptoBalances({ balances }: CryptoBalancesProps) {
  if (!balances || balances.balances.length === 0) {
    return (
      <div className="crypto-balances-empty">
        <p className="muted-text">No crypto holdings</p>
      </div>
    );
  }

  const totalPnlClass = balances.total_unrealized_pnl >= 0 ? "positive" : "negative";

  return (
    <div className="crypto-balances">
      <div className="balances-header">
        <h3>🪙 Crypto Holdings</h3>
        <div className="balances-summary">
          <span className="summary-item">
            <span className="summary-label">Total Value:</span>
            <span className="summary-value">{formatUsd(balances.total_current_value)}</span>
          </span>
          <span className="summary-item">
            <span className="summary-label">Unrealized P/L:</span>
            <span className={`summary-value ${totalPnlClass}`}>
              {formatUsd(balances.total_unrealized_pnl)}
            </span>
          </span>
        </div>
      </div>

      <div className="balances-list">
        {balances.balances.map((balance) => {
          const pnlClass = balance.unrealized_pnl >= 0 ? "positive" : "negative";
          const priceDigits = balance.current_price < 1 ? 6 : 2;

          return (
            <div key={balance.symbol} className="balance-card">
              <div className="balance-header">
                <span className="balance-symbol">{balance.symbol.replace("USDT", "").replace("BTC", "/BTC")}</span>
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
                  <span className="balance-label">Current:</span>
                  <span className="balance-value mono">
                    $
                    {balance.current_price.toLocaleString("en-US", {
                      minimumFractionDigits: priceDigits,
                      maximumFractionDigits: priceDigits,
                    })}
                  </span>
                </div>

                <div className="balance-row">
                  <span className="balance-label">Value:</span>
                  <span className="balance-value mono">{formatUsd(balance.current_value)}</span>
                </div>
              </div>

              {balance.positions.length > 1 && (
                <div className="balance-positions">
                  <span className="positions-label">{balance.positions.length} positions</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

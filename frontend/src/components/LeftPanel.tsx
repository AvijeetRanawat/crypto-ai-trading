import { useEffect, useMemo, useRef, useState } from "react";
import { Chart, type ChartData, registerables } from "chart.js";
import { ColorType, CrosshairMode, createChart, type UTCTimestamp } from "lightweight-charts";
import type {
  MarketPoint,
  PortfolioSummary,
  RlCostSummary,
  RlTuningSnapshot,
  RlWeightsSnapshot,
  SignalEvent,
  Trade,
  WarmupData,
} from "../types/dashboard";
import { formatPair, formatPct, formatUsd } from "../utils/format";
import { getThemeTokens } from "../utils/theme";
import { RlAgentModal } from "./RlAgentModal";

Chart.register(...registerables);

interface LeftPanelProps {
  theme: "light" | "dark";
  selectedSymbol: string;
  symbolOptions: string[];
  onSelectSymbol: (symbol: string) => void;
  warmup: WarmupData;
  marketHistory: MarketPoint[];
  summary: PortfolioSummary;
  signals: SignalEvent[];
  trades: Trade[];
  rlCostSummary: RlCostSummary;
  rlWeights: RlWeightsSnapshot;
  rlTuning: RlTuningSnapshot;
  tradingMode: string;
}

interface PerfSummary {
  text: string;
  cls: "positive" | "negative" | "neutral";
  showEmpty: boolean;
}

function buildPerfSummary(trades: Trade[]): PerfSummary {
  if (!trades.length) {
    return { text: "", cls: "neutral", showEmpty: true };
  }
  const pnls = trades.map((trade) => Number(trade.pnl || 0));
  const wins = pnls.filter((value) => value > 0).length;
  const net = pnls.reduce((acc, value) => acc + value, 0);
  return {
    text: `${wins}W / ${pnls.length - wins}L · Net: ${formatUsd(net)}`,
    cls: net >= 0 ? "positive" : "negative",
    showEmpty: false,
  };
}

function getPriceDigits(price: number): number {
  if (!Number.isFinite(price) || price <= 0) return 2;
  if (price >= 1000) return 0;
  if (price >= 100) return 2;
  if (price >= 1) return 3;
  if (price >= 0.1) return 5;
  if (price >= 0.01) return 6;
  return 8;
}

export function LeftPanel({
  theme,
  selectedSymbol,
  symbolOptions,
  onSelectSymbol,
  warmup,
  marketHistory,
  summary,
  signals,
  trades,
  rlCostSummary,
  rlWeights,
  rlTuning,
  tradingMode,
}: LeftPanelProps) {
  type ChartApi = ReturnType<typeof createChart>;
  type LineSeriesApi = ReturnType<ChartApi["addLineSeries"]>;
  type HistogramSeriesApi = ReturnType<ChartApi["addHistogramSeries"]>;

  const priceChartRef = useRef<ChartApi | null>(null);
  const priceSeriesRef = useRef<LineSeriesApi | null>(null);
  const signalChartRef = useRef<ChartApi | null>(null);
  const buySeriesRef = useRef<HistogramSeriesApi | null>(null);
  const sellSeriesRef = useRef<HistogramSeriesApi | null>(null);
  const perfChartRef = useRef<Chart<"bar"> | null>(null);

  const priceContainerRef = useRef<HTMLDivElement | null>(null);
  const signalContainerRef = useRef<HTMLDivElement | null>(null);
  const perfCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [rlExpanded, setRlExpanded] = useState(false);

  const latestSignal = signals.length ? signals[signals.length - 1] : null;

  const currentPrice = useMemo(() => {
    if (!marketHistory.length) return 0;
    return Number(marketHistory[marketHistory.length - 1].price || 0);
  }, [marketHistory]);

  const priceChange = useMemo(() => {
    if (!marketHistory.length) return 0;
    const latest = Number(marketHistory[marketHistory.length - 1].price || 0);
    const baseIdx = Math.max(0, marketHistory.length - 12);
    const base = Number(marketHistory[baseIdx].price || latest || 1);
    if (!base) return 0;
    return ((latest - base) / base) * 100;
  }, [marketHistory]);

  const priceDigits = useMemo(() => getPriceDigits(currentPrice), [currentPrice]);

  const perfSummary = useMemo(() => buildPerfSummary(trades), [trades]);
  const signalConfidence = useMemo(() => {
    if (!latestSignal) {
      return { buyPct: 0, sellPct: 0 };
    }
    const weightedBuy = Number(latestSignal.weighted_buy ?? latestSignal.buy_votes ?? 0);
    const weightedSell = Number(latestSignal.weighted_sell ?? latestSignal.sell_votes ?? 0);
    const totalWeight = Number(latestSignal.total_weight ?? (weightedBuy + weightedSell));
    const denom = Math.max(1, totalWeight);
    return {
      buyPct: Math.min(100, (weightedBuy / denom) * 100),
      sellPct: Math.min(100, (weightedSell / denom) * 100),
    };
  }, [latestSignal]);

  useEffect(() => {
    if (!priceContainerRef.current || !signalContainerRef.current || priceChartRef.current) return;

    const tokens = getThemeTokens();
    const priceContainer = priceContainerRef.current;
    const signalContainer = signalContainerRef.current;

    const chartHeight = Math.max((priceContainer.parentElement?.clientHeight || 300) - 56, 240);
    priceContainer.style.height = `${chartHeight}px`;

    const priceChart = createChart(priceContainer, {
      width: priceContainer.clientWidth,
      height: chartHeight,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: tokens.chartText },
      grid: { vertLines: { color: tokens.chartGrid }, horzLines: { color: tokens.chartGrid } },
      rightPriceScale: { borderColor: tokens.chartBorder },
      timeScale: { borderColor: tokens.chartBorder, timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const priceSeries = priceChart.addLineSeries({
      color: "#3b82f6",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 0, minMove: 1 },
      lastValueVisible: true,
      priceLineColor: "#3b82f6",
    });

    const signalChart = createChart(signalContainer, {
      width: signalContainer.clientWidth,
      height: 120,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: tokens.chartText },
      grid: { vertLines: { color: tokens.chartGrid }, horzLines: { color: tokens.chartGrid } },
      rightPriceScale: { borderColor: tokens.chartBorder, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: tokens.chartBorder, timeVisible: true, secondsVisible: false, visible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const buySeries = signalChart.addHistogramSeries({
      color: "rgba(34,197,94,0.6)",
      priceFormat: { type: "volume" },
    });
    const sellSeries = signalChart.addHistogramSeries({
      color: "rgba(239,68,68,0.6)",
      priceFormat: { type: "volume" },
    });

    let syncing = false;
    const sync = (src: ChartApi, dest: ChartApi) => {
      src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncing) return;
        syncing = true;
        dest.timeScale().setVisibleLogicalRange(range);
        syncing = false;
      });
    };
    sync(priceChart, signalChart);
    sync(signalChart, priceChart);

    const observer = new ResizeObserver(() => {
      const width = priceContainer.clientWidth;
      const height = Math.max((priceContainer.parentElement?.clientHeight || 300) - 56, 240);
      const signalWidth = signalContainer.clientWidth;
      priceContainer.style.height = `${height}px`;
      if (width > 0 && height > 0) priceChart.applyOptions({ width, height });
      if (signalWidth > 0) signalChart.applyOptions({ width: signalWidth });
    });

    observer.observe(priceContainer);
    observer.observe(signalContainer);

    priceChartRef.current = priceChart;
    priceSeriesRef.current = priceSeries;
    signalChartRef.current = signalChart;
    buySeriesRef.current = buySeries;
    sellSeriesRef.current = sellSeries;

    return () => {
      observer.disconnect();
      priceChart.remove();
      signalChart.remove();
      priceChartRef.current = null;
      priceSeriesRef.current = null;
      signalChartRef.current = null;
      buySeriesRef.current = null;
      sellSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!priceSeriesRef.current || !marketHistory.length) return;

    const series = marketHistory
      .map((point) => ({
        time: Math.floor(new Date(point.timestamp).getTime() / 1000) as UTCTimestamp,
        value: Number(point.price || 0),
      }))
      .filter((point) => point.time > 0)
      .sort((a, b) => a.time - b.time);

    const deduped = new Map<number, { time: UTCTimestamp; value: number }>();
    series.forEach((point) => deduped.set(Number(point.time), point));
    const unique = Array.from(deduped.values());

    if (unique.length) priceSeriesRef.current.setData(unique);
  }, [marketHistory]);

  useEffect(() => {
    if (!priceSeriesRef.current) return;
    const minMove = Number((1 / 10 ** priceDigits).toFixed(priceDigits));
    priceSeriesRef.current.applyOptions({
      priceFormat: { type: "price", precision: priceDigits, minMove },
    });
  }, [priceDigits]);

  useEffect(() => {
    if (!buySeriesRef.current || !sellSeriesRef.current || !priceSeriesRef.current || !signals.length) return;

    const history = signals
      .map((signal) => ({
        time: Math.floor(new Date(signal.timestamp).getTime() / 1000) as UTCTimestamp,
        buy: Number(signal.weighted_buy ?? signal.buy_votes ?? 0),
        sell: Number(signal.weighted_sell ?? signal.sell_votes ?? 0),
        total: Number(signal.total_weight ?? ((signal.weighted_buy ?? signal.buy_votes ?? 0) + (signal.weighted_sell ?? signal.sell_votes ?? 0))),
      }))
      .filter((point) => point.time > 0)
      .sort((a, b) => a.time - b.time);

    const signalByTime = new Map<number, { time: UTCTimestamp; buy: number; sell: number; total: number }>();
    history.forEach((point) => signalByTime.set(Number(point.time), point));
    const uniqueHistory = Array.from(signalByTime.values());

    buySeriesRef.current.setData(
      uniqueHistory.map((point) => {
        const denom = Math.max(1, point.total);
        const buyPct = Math.min(100, (point.buy / denom) * 100);
        return { time: point.time, value: buyPct };
      }),
    );
    sellSeriesRef.current.setData(
      uniqueHistory.map((point) => {
        const denom = Math.max(1, point.total);
        const sellPct = Math.min(100, (point.sell / denom) * 100);
        return { time: point.time, value: -sellPct };
      }),
    );

    const traded = signals.filter((signal) => signal.outcome === "TRADED");
    const missed = signals.filter((signal) => signal.outcome === "MISSED");
    type ChartMarker = {
      time: UTCTimestamp;
      position: "aboveBar" | "belowBar";
      color: string;
      shape: "circle" | "arrowUp" | "arrowDown";
      text: string;
    };

    const markerMap = new Map<number, ChartMarker>();

    missed.forEach((signal) => {
      const time = Math.floor(new Date(signal.timestamp).getTime() / 1000);
      if (time > 0) {
        markerMap.set(time, {
          time: time as UTCTimestamp,
          position: "aboveBar",
          color: "#f59e0b",
          shape: "circle",
          text: "MISSED",
        });
      }
    });

    traded.forEach((signal) => {
      const time = Math.floor(new Date(signal.timestamp).getTime() / 1000);
      if (time > 0) {
        const action = String(signal.claude_action || "").toUpperCase();
        const isLong = action === "LONG" || action === "BUY";
        markerMap.set(time, {
          time: time as UTCTimestamp,
          position: isLong ? "belowBar" : "aboveBar",
          color: "#22c55e",
          shape: isLong ? "arrowUp" : "arrowDown",
          text: `${action || "TRADED"} ${(Number(signal.claude_conf || 0) * 100).toFixed(0)}%`,
        });
      }
    });

    const markers = Array.from(markerMap.values()).sort((a, b) => Number(a.time) - Number(b.time));
    priceSeriesRef.current.setMarkers(markers);
  }, [signals]);

  useEffect(() => {
    if (!perfCanvasRef.current || perfChartRef.current) return;

    const tokens = getThemeTokens();
    const chart = new Chart(perfCanvasRef.current.getContext("2d")!, {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          {
            label: "Trade PnL ($)",
            data: [],
            backgroundColor: [],
            borderRadius: 4,
            borderSkipped: false,
          },
        ],
      } as ChartData<"bar">,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `PnL: $${Number(ctx.raw || 0).toFixed(2)}`,
              title: (ctx) => `Trade ${ctx[0].label}`,
            },
          },
        },
        scales: {
          x: { display: false },
          y: {
            ticks: { color: tokens.chartYTick, callback: (value) => `$${value}` },
            grid: { color: tokens.chartGrid },
            border: { color: tokens.chartBorder },
          },
        },
      },
    });

    perfChartRef.current = chart;
    return () => {
      chart.destroy();
      perfChartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!perfChartRef.current) return;

    const chart = perfChartRef.current;
    if (!trades.length) {
      chart.data.labels = [];
      chart.data.datasets[0].data = [];
      chart.data.datasets[0].backgroundColor = [];
      chart.update("none");
      return;
    }

    const orderedTrades = [...trades].reverse();
    const labels = orderedTrades.map((_, idx) => `#${idx + 1}`);
    const pnls = orderedTrades.map((trade) => Number(Number(trade.pnl || 0).toFixed(2)));
    const colors = pnls.map((pnl) => (pnl >= 0 ? "rgba(34,197,94,0.8)" : "rgba(239,68,68,0.8)"));

    chart.data.labels = labels;
    chart.data.datasets[0].data = pnls;
    chart.data.datasets[0].backgroundColor = colors;
    chart.update("none");
  }, [trades]);

  useEffect(() => {
    const tokens = getThemeTokens();

    if (priceChartRef.current) {
      priceChartRef.current.applyOptions({
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: tokens.chartText },
        grid: { vertLines: { color: tokens.chartGrid }, horzLines: { color: tokens.chartGrid } },
        rightPriceScale: { borderColor: tokens.chartBorder },
        timeScale: { borderColor: tokens.chartBorder },
      });
    }

    if (signalChartRef.current) {
      signalChartRef.current.applyOptions({
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: tokens.chartText },
        grid: { vertLines: { color: tokens.chartGrid }, horzLines: { color: tokens.chartGrid } },
        rightPriceScale: { borderColor: tokens.chartBorder, scaleMargins: { top: 0.1, bottom: 0.1 } },
        timeScale: { borderColor: tokens.chartBorder, timeVisible: true, secondsVisible: false, visible: false },
      });
    }

    if (perfChartRef.current) {
      perfChartRef.current.options.scales!.y!.ticks!.color = tokens.chartYTick;
      perfChartRef.current.options.scales!.y!.grid!.color = tokens.chartGrid;
      perfChartRef.current.options.scales!.y!.border!.color = tokens.chartBorder;
      perfChartRef.current.update("none");
    }
  }, [theme]);

  return (
    <div className="chart-area">
      <div className="price-ticker">
        <span className="pair">{formatPair(selectedSymbol)}</span>
        <select
          className="symbol-select"
          value={selectedSymbol}
          onChange={(e) => onSelectSymbol(e.target.value)}
        >
          {symbolOptions.map((symbol) => (
            <option key={symbol} value={symbol}>
              {formatPair(symbol)}
            </option>
          ))}
        </select>
        <span className="live-price">
          ${currentPrice.toLocaleString("en-US", {
            minimumFractionDigits: priceDigits,
            maximumFractionDigits: priceDigits,
          })}
        </span>
        <span className={`live-change ${priceChange >= 0 ? "positive" : "negative"}`}>
          {formatPct(priceChange)}
        </span>
        <div className="open-positions-container">
          {summary.open_positions && summary.open_positions.length > 0 ? (
            summary.open_positions.map((pos) => {
              const posPrice = Number(pos.entry_price || 0);
              const posPriceDigits = posPrice < 1 ? 6 : 2;
              const mode = pos.mode || 'SPOT';
              return (
                <span
                  key={pos.id}
                  className={`open-pos-badge ${
                    String(pos.side || "").toUpperCase() === "LONG" ? "positive" : "negative"
                  }`}
                >
                  {mode} {pos.side} {pos.symbol} @ ${posPrice.toLocaleString("en-US", {
                    minimumFractionDigits: posPriceDigits,
                    maximumFractionDigits: posPriceDigits,
                  })}
                </span>
              );
            })
          ) : (
            <span className="open-pos-badge neutral">No open positions</span>
          )}
        </div>
        <div className="legend">
          <span className="legend-item">
            <span className="legend-dot traded" />Traded
          </span>
          <span className="legend-item">
            <span className="legend-dot missed" />Missed
          </span>
        </div>
      </div>

      {!warmup.done && (
        <div className="warmup-wrap">
          <div className="warmup-track">
            <div className="warmup-bar" style={{ width: `${Number(warmup.pct || 0)}%` }} />
          </div>
          <span className="warmup-label">
            Warming up... {warmup.ticks || 0}/{warmup.min_ticks || 35} ticks · ~
            {warmup.seconds_remaining || 0}s remaining
          </span>
        </div>
      )}

      <div className="chart-wrap glass">
        <div className="chart-label-row">
          <span className="chart-label">PRICE CHART · LIVE</span>
          <span className="ta-badge">RSI {latestSignal?.rsi != null ? latestSignal.rsi.toFixed(1) : "-"}</span>
          <span className="ta-badge">MACD {latestSignal?.macd || "-"}</span>
          <span className="ta-badge">BB {latestSignal?.bb_pct != null ? `${latestSignal.bb_pct.toFixed(0)}%` : "-"}</span>
        </div>
        <div id="priceChart" ref={priceContainerRef} />
      </div>

      <div className="signal-panel glass">
        <div className="chart-label-row">
          <span className="chart-label">SIGNAL INTELLIGENCE</span>
          <span className="legend-inline">
            <span style={{ color: "var(--green)" }}>BUY {signalConfidence.buyPct.toFixed(0)}%</span>
            <span style={{ color: "var(--red)" }}>SELL {signalConfidence.sellPct.toFixed(0)}%</span>
            <span style={{ color: "var(--yellow)" }}>MISSED</span>
            <span style={{ color: "var(--accent)" }}>TRADED</span>
          </span>
        </div>
        <div id="signalChart" ref={signalContainerRef} />
      </div>

      <div className="bottom-row">
        <div className="equity-card glass">
          <div className="card-label">
            TRADE PERFORMANCE
            <span className={`perf-summary ${perfSummary.cls}`}> {perfSummary.text}</span>
          </div>
          {perfSummary.showEmpty && <div className="perf-empty">No trades yet - waiting for first signal</div>}
          <canvas id="perfChart" ref={perfCanvasRef} />
        </div>

        <div className="trades-card glass">
          <div className="card-label">RECENT TRADES</div>
          <div className="trades-list">
            {!trades.length && <div className="empty-state">No trades yet this session</div>}
            {trades.slice(0, 15).map((trade, idx) => {
              const pnl = Number(trade.pnl || 0);
              const pnlClass = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral";
              const side = String(trade.side || "").toUpperCase();
              const sideIcon = side === "LONG" ? "UP" : "DOWN";
              const time = trade.entry_time ? String(trade.entry_time).slice(11, 16) : "--:--";

              return (
                <div className={`trade-row ${pnlClass}`} key={`${trade.id || idx}-${time}`}>
                  <span className={`trade-side ${side === "LONG" ? "buy" : "sell"}`}>{sideIcon} {side}</span>
                  <span className="trade-price">
                    ${Number(trade.price || 0).toLocaleString("en-US", {
                      minimumFractionDigits: priceDigits,
                      maximumFractionDigits: priceDigits,
                    })}
                  </span>
                  <span className={`trade-pnl ${pnlClass}`}>
                    {pnl !== 0 ? formatUsd(pnl) : trade.status || "-"}
                  </span>
                  <span className="trade-time">{time}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="rl-cost-card glass">
          <div className="section-header rl-header">
            <span>RL AGENT</span>
            <button className="expand-btn" onClick={() => setRlExpanded(true)} type="button">
              Expand
            </button>
          </div>
          <div className="rl-cost-grid">
            <div className="rl-cost-row">
              <span>Session Events</span>
              <span>{rlCostSummary.session.events}</span>
            </div>
            <div className="rl-cost-row">
              <span>Session Penalty</span>
              <span className="negative">{formatUsd(-Math.abs(rlCostSummary.session.total_penalty))}</span>
            </div>
            <div className="rl-cost-row">
              <span>Skip Penalty</span>
              <span className="negative">{formatUsd(-Math.abs(rlCostSummary.session.skip_penalty))}</span>
            </div>
            <div className="rl-cost-row">
              <span>Hold Penalty</span>
              <span className="negative">{formatUsd(-Math.abs(rlCostSummary.session.hold_penalty))}</span>
            </div>
            <div className="rl-cost-row">
              <span>Reward</span>
              <span className={rlCostSummary.session.total_reward >= 0 ? "positive" : "negative"}>
                {formatUsd(rlCostSummary.session.total_reward)}
              </span>
            </div>
          </div>
        </div>
      </div>
      <RlAgentModal
        open={rlExpanded}
        mode={tradingMode}
        weights={rlWeights}
        tuning={rlTuning}
        onClose={() => setRlExpanded(false)}
      />
    </div>
  );
}

const { useEffect, useMemo, useRef, useState } = React;

const API = "/api";
const THEME_KEY = "dashboard-theme";
const PANEL_WIDTH_KEY = "ai-panel-width";
const SESSION_START_KEY = "tradingSessionStart";
const SESSION_START_MS_KEY = "tradingSessionStartMs";

function fetchJson(path) {
    return fetch(path)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
}

function getThemeTokens() {
    const css = getComputedStyle(document.documentElement);
    return {
        chartText: css.getPropertyValue("--chart-text").trim() || "#71717a",
        chartGrid: css.getPropertyValue("--chart-grid").trim() || "rgba(255,255,255,0.03)",
        chartBorder: css.getPropertyValue("--chart-border").trim() || "rgba(255,255,255,0.08)",
        chartYTick: css.getPropertyValue("--chart-y-tick").trim() || "#4b5563",
    };
}

function formatUsd(n) {
    const value = Number(n || 0);
    const sign = value >= 0 ? "+" : "-";
    return `${sign}$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatNum(n) {
    return Number(n || 0).toLocaleString("en-US");
}

function formatPct(n) {
    const value = Number(n || 0);
    return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function uptimeString(startMs, nowMs) {
    const sec = Math.max(0, Math.floor((nowMs - startMs) / 1000));
    const hh = String(Math.floor(sec / 3600)).padStart(2, "0");
    const mm = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
    const ss = String(sec % 60).padStart(2, "0");
    return `${hh}:${mm}:${ss}`;
}

function useTheme() {
    const [theme, setTheme] = useState(() => {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved === "light" || saved === "dark") return saved;
        const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        return prefersDark ? "dark" : "light";
    });

    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem(THEME_KEY, theme);
    }, [theme]);

    return [theme, setTheme];
}

function App() {
    const [theme, setTheme] = useTheme();
    const [nowMs, setNowMs] = useState(Date.now());
    const [startTimeMs, setStartTimeMs] = useState(() => {
        const stored = localStorage.getItem(SESSION_START_MS_KEY);
        return stored ? Number(stored) : Date.now();
    });

    const [panelWidth, setPanelWidth] = useState(() => {
        const saved = localStorage.getItem(PANEL_WIDTH_KEY);
        return saved ? Number(saved) : 300;
    });

    const [warmup, setWarmup] = useState({ done: false, ticks: 0, min_ticks: 35, pct: 0, seconds_remaining: 0 });
    const [marketHistory, setMarketHistory] = useState([]);
    const [summary, setSummary] = useState({
        total_pnl: 0,
        win_rate: 0,
        total_trades: 0,
        missed_count: 0,
        llm_cost_today: 0,
        llm_cost_per_traded_signal: null,
        llm_cost_per_dollar_pnl: null,
        llm_trade_conversion_rate: 0,
        open_position: null,
    });
    const [signals, setSignals] = useState([]);
    const [trades, setTrades] = useState([]);
    const [lessons, setLessons] = useState([]);
    const [intent, setIntent] = useState({ message: "Initializing...", targets: [] });
    const [regime, setRegime] = useState({
        regime: "WARMING_UP",
        verdict: "Loading...",
        atr_verdict: "ATR: -",
        session: "-",
        session_quality: "LOW",
        session_verdict: "Loading session window...",
    });
    const [logs, setLogs] = useState("...");
    const [llmSummary, setLlmSummary] = useState({
        llm_tokens_session: 0,
        llm_tokens_today: 0,
        llm_tokens_all_time: 0,
        llm_calls_all_time: 0,
    });

    const sessionStartRef = useRef(localStorage.getItem(SESSION_START_KEY) || null);
    const resizingRef = useRef(false);

    const priceChartRef = useRef(null);
    const priceSeriesRef = useRef(null);
    const signalChartRef = useRef(null);
    const buySeriesRef = useRef(null);
    const sellSeriesRef = useRef(null);
    const perfChartRef = useRef(null);

    const priceContainerRef = useRef(null);
    const signalContainerRef = useRef(null);
    const perfCanvasRef = useRef(null);
    const logsRef = useRef(null);

    const latestSignal = signals.length ? signals[signals.length - 1] : null;
    const totalVotes = 8;

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

    const perfSummary = useMemo(() => {
        if (!trades.length) return { text: "", cls: "neutral", showEmpty: true };
        const pnls = trades.map((t) => Number(t.pnl || 0));
        const wins = pnls.filter((p) => p > 0).length;
        const net = pnls.reduce((a, b) => a + b, 0);
        return {
            text: `${wins}W / ${pnls.length - wins}L · Net: ${formatUsd(net)}`,
            cls: net >= 0 ? "positive" : "negative",
            showEmpty: false,
        };
    }, [trades]);

    const balance = 1250 + Number(summary.total_pnl || 0);
    const uptime = uptimeString(startTimeMs, nowMs);

    function resetSessionState() {
        setWarmup({ done: false, ticks: 0, min_ticks: 35, pct: 0, seconds_remaining: 0 });
        setMarketHistory([]);
        setSignals([]);
        setTrades([]);
        setLessons([]);
        setIntent({ message: "New session starting...", targets: [] });
        setLogs("...");
        setSummary({
            total_pnl: 0,
            win_rate: 0,
            total_trades: 0,
            missed_count: 0,
            llm_cost_today: 0,
            llm_cost_per_traded_signal: null,
            llm_cost_per_dollar_pnl: null,
            llm_trade_conversion_rate: 0,
            open_position: null,
        });
    }

    async function syncSessionStart() {
        const data = await fetchJson(`${API}/session_start`);
        if (!data) return;

        if (!sessionStartRef.current) {
            sessionStartRef.current = data.session_start;
            localStorage.setItem(SESSION_START_KEY, data.session_start);
            localStorage.setItem(SESSION_START_MS_KEY, String(data.session_start_ms || Date.now()));
            setStartTimeMs(Number(data.session_start_ms || Date.now()));
            return;
        }

        if (sessionStartRef.current !== data.session_start) {
            sessionStartRef.current = data.session_start;
            localStorage.setItem(SESSION_START_KEY, data.session_start);
            localStorage.setItem(SESSION_START_MS_KEY, String(data.session_start_ms || Date.now()));
            setStartTimeMs(Number(data.session_start_ms || Date.now()));
            resetSessionState();
        }
    }

    useEffect(() => {
        let active = true;

        const fastPoll = async () => {
            await syncSessionStart();
            if (!active) return;
            const [warm, market, portfolio, intentData, signalData, regimeData] = await Promise.all([
                fetchJson(`${API}/warmup`),
                fetchJson(`${API}/market/history?symbol=BTCUSDT`),
                fetchJson(`${API}/portfolio/summary`),
                fetchJson(`${API}/intent`),
                fetchJson(`${API}/signals/history?symbol=BTCUSDT&limit=60`),
                fetchJson(`${API}/regime`),
            ]);
            if (!active) return;
            if (warm) setWarmup(warm);
            if (Array.isArray(market)) setMarketHistory(market);
            if (portfolio) setSummary(portfolio);
            if (intentData) setIntent(intentData);
            if (Array.isArray(signalData)) setSignals(signalData);
            if (regimeData) setRegime(regimeData);
        };

        const slowPoll = async () => {
            const [tradeData, lessonData, logData, usage] = await Promise.all([
                fetchJson(`${API}/trades/recent`),
                fetchJson(`${API}/lessons`),
                fetchJson(`${API}/logs?lines=60`),
                fetchJson(`${API}/llm/summary`),
            ]);
            if (!active) return;
            if (Array.isArray(tradeData)) setTrades(tradeData);
            if (Array.isArray(lessonData)) setLessons(lessonData);
            if (logData && Array.isArray(logData.logs)) setLogs(logData.logs.join("").trim());
            if (usage) setLlmSummary(usage);
        };

        fastPoll();
        slowPoll();

        const tFast = setInterval(fastPoll, 3000);
        const tSlow = setInterval(slowPoll, 8000);
        const tClock = setInterval(() => setNowMs(Date.now()), 1000);

        return () => {
            active = false;
            clearInterval(tFast);
            clearInterval(tSlow);
            clearInterval(tClock);
        };
    }, []);

    useEffect(() => {
        if (!logsRef.current) return;
        logsRef.current.scrollTop = logsRef.current.scrollHeight;
    }, [logs]);

    useEffect(() => {
        const onMouseMove = (e) => {
            if (!resizingRef.current) return;
            const width = window.innerWidth - e.clientX - 12;
            if (width > 150 && width < 600) {
                setPanelWidth(width);
                localStorage.setItem(PANEL_WIDTH_KEY, String(Math.round(width)));
            }
        };
        const onMouseUp = () => {
            if (!resizingRef.current) return;
            resizingRef.current = false;
            document.body.style.cursor = "default";
        };
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
        return () => {
            document.removeEventListener("mousemove", onMouseMove);
            document.removeEventListener("mouseup", onMouseUp);
        };
    }, []);

    useEffect(() => {
        if (!priceContainerRef.current || !signalContainerRef.current || priceChartRef.current) return;

        const t = getThemeTokens();
        const priceContainer = priceContainerRef.current;
        const signalContainer = signalContainerRef.current;

        const chartHeight = Math.max((priceContainer.parentElement?.clientHeight || 300) - 56, 240);
        priceContainer.style.height = `${chartHeight}px`;

        const priceChart = LightweightCharts.createChart(priceContainer, {
            width: priceContainer.clientWidth,
            height: chartHeight,
            layout: { background: { type: "solid", color: "transparent" }, textColor: t.chartText },
            grid: { vertLines: { color: t.chartGrid }, horzLines: { color: t.chartGrid } },
            rightPriceScale: { borderColor: t.chartBorder },
            timeScale: { borderColor: t.chartBorder, timeVisible: true, secondsVisible: false },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        });

        const priceSeries = priceChart.addLineSeries({
            color: "#3b82f6",
            lineWidth: 2,
            priceFormat: { type: "price", precision: 0, minMove: 1 },
            lastValueVisible: true,
            priceLineColor: "#3b82f6",
        });

        const signalChart = LightweightCharts.createChart(signalContainer, {
            width: signalContainer.clientWidth,
            height: 120,
            layout: { background: { type: "solid", color: "transparent" }, textColor: t.chartText },
            grid: { vertLines: { display: false }, horzLines: { color: t.chartGrid } },
            rightPriceScale: { borderColor: t.chartBorder, scaleMargins: { top: 0.1, bottom: 0.1 } },
            timeScale: { borderColor: t.chartBorder, timeVisible: true, secondsVisible: false, visible: false },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        });

        const buySeries = signalChart.addHistogramSeries({ color: "rgba(34,197,94,0.6)", priceFormat: { type: "volume" } });
        const sellSeries = signalChart.addHistogramSeries({ color: "rgba(239,68,68,0.6)", priceFormat: { type: "volume" } });

        let syncing = false;
        const sync = (src, dest) => {
            src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
                if (syncing) return;
                syncing = true;
                dest.timeScale().setVisibleLogicalRange(range);
                syncing = false;
            });
        };
        sync(priceChart, signalChart);
        sync(signalChart, priceChart);

        const ro = new ResizeObserver(() => {
            const w = priceContainer.clientWidth;
            const h = Math.max((priceContainer.parentElement?.clientHeight || 300) - 56, 240);
            const sw = signalContainer.clientWidth;
            priceContainer.style.height = `${h}px`;
            if (w > 0 && h > 0) priceChart.applyOptions({ width: w, height: h });
            if (sw > 0) signalChart.applyOptions({ width: sw });
        });
        ro.observe(priceContainer);
        ro.observe(signalContainer);

        priceChartRef.current = priceChart;
        priceSeriesRef.current = priceSeries;
        signalChartRef.current = signalChart;
        buySeriesRef.current = buySeries;
        sellSeriesRef.current = sellSeries;

        return () => {
            ro.disconnect();
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
            .map((d) => ({
                time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                value: Number(d.price || 0),
            }))
            .filter((d) => d.time > 0)
            .sort((a, b) => a.time - b.time);

        const byTime = new Map();
        series.forEach((pt) => byTime.set(pt.time, pt));
        const unique = Array.from(byTime.values());
        if (unique.length) priceSeriesRef.current.setData(unique);
    }, [marketHistory]);

    useEffect(() => {
        if (!buySeriesRef.current || !sellSeriesRef.current || !priceSeriesRef.current) return;
        if (!signals.length) return;

        const history = signals
            .map((d) => ({
                time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                buy: Number(d.buy_votes || 0),
                sell: Number(d.sell_votes || 0),
            }))
            .filter((d) => d.time > 0)
            .sort((a, b) => a.time - b.time);

        buySeriesRef.current.setData(history.map((h) => ({ time: h.time, value: h.buy })));
        sellSeriesRef.current.setData(history.map((h) => ({ time: h.time, value: -h.sell })));

        const traded = signals.filter((d) => d.outcome === "TRADED");
        const missed = signals.filter((d) => d.outcome === "MISSED");
        const markerMap = new Map();

        missed.forEach((d) => {
            const t = Math.floor(new Date(d.timestamp).getTime() / 1000);
            if (t > 0) {
                markerMap.set(t, {
                    time: t,
                    position: "aboveBar",
                    color: "#f59e0b",
                    shape: "circle",
                    text: "MISSED",
                });
            }
        });

        traded.forEach((d) => {
            const t = Math.floor(new Date(d.timestamp).getTime() / 1000);
            if (t > 0) {
                const action = String(d.claude_action || "").toUpperCase();
                const isLong = action === "LONG" || action === "BUY";
                markerMap.set(t, {
                    time: t,
                    position: isLong ? "belowBar" : "aboveBar",
                    color: "#22c55e",
                    shape: isLong ? "arrowUp" : "arrowDown",
                    text: `${action || "TRADED"} ${((Number(d.claude_conf || 0)) * 100).toFixed(0)}%`,
                });
            }
        });

        const markers = Array.from(markerMap.values()).sort((a, b) => a.time - b.time);
        priceSeriesRef.current.setMarkers(markers);
    }, [signals]);

    useEffect(() => {
        if (!perfCanvasRef.current || perfChartRef.current) return;
        const t = getThemeTokens();
        const chart = new Chart(perfCanvasRef.current.getContext("2d"), {
            type: "bar",
            data: {
                labels: [],
                datasets: [{
                    label: "Trade PnL ($)",
                    data: [],
                    backgroundColor: [],
                    borderRadius: 4,
                    borderSkipped: false,
                }],
            },
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
                        ticks: { color: t.chartYTick, callback: (v) => `$${v}` },
                        grid: { color: t.chartGrid },
                        border: { color: t.chartBorder },
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
        const ordered = [...trades].reverse();
        const labels = ordered.map((_, i) => `#${i + 1}`);
        const pnls = ordered.map((t) => Number(t.pnl || 0).toFixed(2)).map(Number);
        const colors = pnls.map((p) => (p >= 0 ? "rgba(34,197,94,0.8)" : "rgba(239,68,68,0.8)"));
        chart.data.labels = labels;
        chart.data.datasets[0].data = pnls;
        chart.data.datasets[0].backgroundColor = colors;
        chart.update("none");
    }, [trades]);

    useEffect(() => {
        const t = getThemeTokens();
        if (priceChartRef.current) {
            priceChartRef.current.applyOptions({
                layout: { background: { type: "solid", color: "transparent" }, textColor: t.chartText },
                grid: { vertLines: { color: t.chartGrid }, horzLines: { color: t.chartGrid } },
                rightPriceScale: { borderColor: t.chartBorder },
                timeScale: { borderColor: t.chartBorder },
            });
        }
        if (signalChartRef.current) {
            signalChartRef.current.applyOptions({
                layout: { background: { type: "solid", color: "transparent" }, textColor: t.chartText },
                grid: { vertLines: { display: false }, horzLines: { color: t.chartGrid } },
                rightPriceScale: { borderColor: t.chartBorder, scaleMargins: { top: 0.1, bottom: 0.1 } },
                timeScale: { borderColor: t.chartBorder, timeVisible: true, secondsVisible: false, visible: false },
            });
        }
        if (perfChartRef.current) {
            perfChartRef.current.options.scales.y.ticks.color = t.chartYTick;
            perfChartRef.current.options.scales.y.grid.color = t.chartGrid;
            perfChartRef.current.options.scales.y.border.color = t.chartBorder;
            perfChartRef.current.update("none");
        }
    }, [theme]);

    const regimeClass = {
        BULL: "regime-bull",
        BEAR: "regime-bear",
        CHOPPY: "regime-choppy",
        NEUTRAL: "regime-neutral",
        UNKNOWN: "regime-neutral",
        WARMING_UP: "regime-neutral",
        ERROR: "regime-neutral",
    }[regime.regime] || "regime-neutral";

    const sessionClass = {
        PREMIUM: "sess-premium",
        HIGH: "sess-high",
        MODERATE: "sess-moderate",
        LOW: "sess-low",
    }[regime.session_quality] || "sess-low";

    const pnlClass = Number(summary.total_pnl || 0) >= 0 ? "positive" : "negative";

    return (
        <div className="app">
            <header className="topbar">
                <div className="topbar-left">
                    <div className="dot-live"></div>
                    <span className="brand-name">AI Trading Terminal</span>
                    <span className="mode-badge">SIMULATION · React</span>
                </div>
                <div className="topbar-right">
                    <button
                        id="theme-toggle"
                        className="theme-toggle"
                        type="button"
                        aria-label="Toggle theme"
                        onClick={() => setTheme(theme === "light" ? "dark" : "light")}
                    >
                        {theme === "light" ? "Dark" : "Light"}
                    </button>
                    <div className="stat-pill">
                        <span className="pill-label">BALANCE</span>
                        <span className="pill-value">${balance.toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">P/L</span>
                        <span className={`pill-value ${pnlClass}`}>{formatUsd(summary.total_pnl)}</span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">WIN RATE</span>
                        <span className="pill-value">{summary.total_trades > 0 ? `${Number(summary.win_rate || 0).toFixed(1)}%` : "--%"}</span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">TRADES</span>
                        <span className="pill-value mono">{summary.total_trades || 0}</span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">MISSED</span>
                        <span className="pill-value mono" style={{ color: "var(--yellow)" }}>{summary.missed_count || 0}</span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">LLM $/DAY</span>
                        <span className="pill-value mono">${Number(summary.llm_cost_today || 0).toFixed(4)}</span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">LLM $/TRADE</span>
                        <span className="pill-value mono">
                            {summary.llm_cost_per_traded_signal != null ? `$${Number(summary.llm_cost_per_traded_signal).toFixed(4)}` : "-"}
                        </span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">LLM $/$PNL</span>
                        <span className="pill-value mono">
                            {summary.llm_cost_per_dollar_pnl != null ? `${Number(summary.llm_cost_per_dollar_pnl).toFixed(4)}x` : "-"}
                        </span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">LLM CONV</span>
                        <span className="pill-value mono">{Number(summary.llm_trade_conversion_rate || 0).toFixed(1)}%</span>
                    </div>
                    <div className="stat-pill">
                        <span className="pill-label">UPTIME</span>
                        <span className="pill-value mono">{uptime}</span>
                    </div>
                </div>
            </header>

            <main className="dashboard">
                <div className="chart-area">
                    <div className="price-ticker">
                        <span className="pair">BTC / USDT</span>
                        <span className="live-price">${currentPrice.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                        <span className={`live-change ${priceChange >= 0 ? "positive" : "negative"}`}>{formatPct(priceChange)}</span>
                        <span className={`open-pos-badge ${summary.open_position ? (String(summary.open_position.side || "").toUpperCase() === "LONG" ? "positive" : "negative") : "neutral"}`}>
                            {summary.open_position
                                ? `${summary.open_position.side} ${summary.open_position.symbol} @ $${Number(summary.open_position.entry_price || 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}`
                                : "No open position"}
                        </span>
                        <div className="legend">
                            <span className="legend-item"><span className="legend-dot traded"></span>Traded</span>
                            <span className="legend-item"><span className="legend-dot missed"></span>Missed</span>
                        </div>
                    </div>

                    {!warmup.done && (
                        <div className="warmup-wrap">
                            <div className="warmup-track">
                                <div className="warmup-bar" style={{ width: `${Number(warmup.pct || 0)}%` }}></div>
                            </div>
                            <span className="warmup-label">
                                Warming up... {warmup.ticks || 0}/{warmup.min_ticks || 35} ticks · ~{warmup.seconds_remaining || 0}s remaining
                            </span>
                        </div>
                    )}

                    <div className="chart-wrap glass">
                        <div className="chart-label-row">
                            <span className="chart-label">PRICE CHART · LIVE</span>
                            <span className="ta-badge">RSI {latestSignal && latestSignal.rsi != null ? Number(latestSignal.rsi).toFixed(1) : "-"}</span>
                            <span className="ta-badge">MACD {latestSignal?.macd || "-"}</span>
                            <span className="ta-badge">BB {latestSignal && latestSignal.bb_pct != null ? `${Number(latestSignal.bb_pct).toFixed(0)}%` : "-"}</span>
                        </div>
                        <div id="priceChart" ref={priceContainerRef}></div>
                    </div>

                    <div className="signal-panel glass">
                        <div className="chart-label-row">
                            <span className="chart-label">SIGNAL INTELLIGENCE</span>
                            <span className="legend-inline">
                                <span style={{ color: "var(--green)" }}>BUY</span>
                                <span style={{ color: "var(--red)" }}>SELL</span>
                                <span style={{ color: "var(--yellow)" }}>MISSED</span>
                                <span style={{ color: "var(--accent)" }}>TRADED</span>
                            </span>
                        </div>
                        <div id="signalChart" ref={signalContainerRef}></div>
                    </div>

                    <div className="bottom-row">
                        <div className="equity-card glass">
                            <div className="card-label">
                                TRADE PERFORMANCE
                                <span className={`perf-summary ${perfSummary.cls}`}> {perfSummary.text}</span>
                            </div>
                            {perfSummary.showEmpty && <div className="perf-empty">No trades yet - waiting for first signal</div>}
                            <canvas id="perfChart" ref={perfCanvasRef}></canvas>
                        </div>
                        <div className="trades-card glass">
                            <div className="card-label">RECENT TRADES</div>
                            <div className="trades-list">
                                {!trades.length && <div className="empty-state">No trades yet this session</div>}
                                {trades.slice(0, 15).map((t, idx) => {
                                    const pnl = Number(t.pnl || 0);
                                    const cls = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral";
                                    const side = String(t.side || "").toUpperCase();
                                    const sideIcon = side === "LONG" ? "UP" : "DOWN";
                                    const time = t.entry_time ? String(t.entry_time).slice(11, 16) : "--:--";
                                    return (
                                        <div className={`trade-row ${cls}`} key={`${t.id || idx}-${time}`}>
                                            <span className={`trade-side ${side === "LONG" ? "buy" : "sell"}`}>{sideIcon} {side}</span>
                                            <span className="trade-price">${Number(t.price || 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                                            <span className={`trade-pnl ${cls}`}>{pnl !== 0 ? formatUsd(pnl) : (t.status || "-")}</span>
                                            <span className="trade-time">{time}</span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>
                </div>

                <div
                    id="v-resizer"
                    className="resizer-v"
                    onMouseDown={(e) => {
                        resizingRef.current = true;
                        document.body.style.cursor = "col-resize";
                        e.preventDefault();
                    }}
                ></div>

                <aside className="ai-panel" style={{ width: `${panelWidth}px` }}>
                    <div className="panel-section glass">
                        <div className="section-header"><span>MARKET REGIME</span></div>
                        <div className="regime-row">
                            <span className={`regime-badge ${regimeClass}`}>{regime.regime || "WARMING_UP"}</span>
                            <div className="regime-detail">
                                <div className="regime-verdict-text">{regime.verdict || "Loading..."}</div>
                                <div className="atr-text">{regime.atr_verdict || "ATR: -"}</div>
                            </div>
                        </div>
                        <div className="session-row">
                            <span className={`sess-badge ${sessionClass}`}>{regime.session || "-"}</span>
                            <div className="sess-verdict-text">{regime.session_verdict || "Loading session window..."}</div>
                        </div>
                    </div>

                    <div className="panel-section glass">
                        <div className="section-header">
                            <div className="pulse-dot"></div>
                            <span>AI INTENT</span>
                        </div>
                        <div className="intent-text">{intent.message || "Initializing..."}</div>
                    </div>

                    <div className="panel-section glass signal-votes-panel">
                        <div className="section-header"><span>LIVE VOTE TALLY</span></div>
                        <div className="vote-meters">
                            <div className="vote-row">
                                <span className="vote-label">BUY</span>
                                <div className="vote-bar-wrap">
                                    <div className="vote-bar buy-bar" style={{ width: `${Math.min(100, ((Number(latestSignal?.buy_votes || 0) / totalVotes) * 100))}%` }}></div>
                                </div>
                                <span className="vote-count positive">{latestSignal?.buy_votes || 0}/{totalVotes}</span>
                            </div>
                            <div className="vote-row">
                                <span className="vote-label">SELL</span>
                                <div className="vote-bar-wrap">
                                    <div className="vote-bar sell-bar" style={{ width: `${Math.min(100, ((Number(latestSignal?.sell_votes || 0) / totalVotes) * 100))}%` }}></div>
                                </div>
                                <span className="vote-count negative">{latestSignal?.sell_votes || 0}/{totalVotes}</span>
                            </div>
                        </div>
                        <div className="ta-grid">
                            <div className="ta-cell"><div className="ta-name">RSI</div><div className="ta-val">{latestSignal && latestSignal.rsi != null ? Number(latestSignal.rsi).toFixed(1) : "-"}</div></div>
                            <div className="ta-cell"><div className="ta-name">MACD</div><div className="ta-val">{latestSignal?.macd || "-"}</div></div>
                            <div className="ta-cell"><div className="ta-name">BB%</div><div className="ta-val">{latestSignal && latestSignal.bb_pct != null ? `${Number(latestSignal.bb_pct).toFixed(0)}%` : "-"}</div></div>
                            <div className="ta-cell"><div className="ta-name">Outcome</div><div className={`ta-val ${latestSignal?.outcome === "TRADED" ? "positive" : latestSignal?.outcome === "MISSED" ? "warn" : "neutral"}`}>{latestSignal?.outcome || "-"}</div></div>
                        </div>
                    </div>

                    <div className="panel-section glass llm-usage-panel">
                        <div className="section-header"><span>LLM TOKEN USAGE</span></div>
                        <div className="llm-usage-grid">
                            <div className="llm-usage-row"><span className="llm-usage-label">Session</span><span className="llm-usage-value mono">{formatNum(llmSummary.llm_tokens_session)}</span></div>
                            <div className="llm-usage-row"><span className="llm-usage-label">Today</span><span className="llm-usage-value mono">{formatNum(llmSummary.llm_tokens_today)}</span></div>
                            <div className="llm-usage-row"><span className="llm-usage-label">All-Time</span><span className="llm-usage-value mono">{formatNum(llmSummary.llm_tokens_all_time)}</span></div>
                            <div className="llm-usage-row"><span className="llm-usage-label">Calls (All-Time)</span><span className="llm-usage-value mono">{formatNum(llmSummary.llm_calls_all_time)}</span></div>
                        </div>
                    </div>

                    <div className="panel-section glass lessons-panel">
                        <div className="section-header"><span>LESSONS LEARNED</span></div>
                        <div className="lessons-list">
                            {!lessons.length && <div className="empty-state">No lessons yet</div>}
                            {lessons.map((l) => {
                                const sev = String(l.severity || "").toUpperCase();
                                const cls = sev === "GOLDEN" ? "lesson-gold" : sev === "WIN" ? "lesson-win" : "lesson-loss";
                                return (
                                    <div className={`lesson-row ${cls}`} key={l.id || `${l.timestamp}-${l.condition}`}>
                                        <span className="lesson-text"><b>{l.condition}</b> -> {l.lesson}</span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </aside>
            </main>

            <section className="logs-bar glass">
                <div className="logs-title">SYSTEM LOG · AUTO-SCROLL</div>
                <pre className="log-body" ref={logsRef}>{logs || "..."}</pre>
            </section>
        </div>
    );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);

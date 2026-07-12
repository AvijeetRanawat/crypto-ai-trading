/* ════════════════════════════════════════════════════════════════════════════
   Crypto AI Trading Terminal — script.js  (Engine v6 Dynamic Dashboard)
   Polls every 3 seconds, detects session restarts, shows regime/ATR/session
   ════════════════════════════════════════════════════════════════════════════ */

const API = "/api";
let priceChart = null, priceSeries = null;
let signalChart = null, buySeries = null, sellSeries = null;
let perfChart = null;
let chartsReady = false;
let startTime = Date.now();
let knownSessionStart = null;
let lastLogLength = 0;
let lastTradeCount = 0;
let warmupDone = false;

// ── INIT ──────────────────────────────────────────────────────────────────────
function initCharts() {
    // 1. LightweightCharts — Price (always visible, never cleared between ticks)
    const container = document.getElementById('priceChart');
    const h = container.parentElement.clientHeight - 56;
    container.style.height = Math.max(h, 240) + 'px';

    priceChart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: +container.style.height.replace('px', ''),
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#71717a' },
        grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
        rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
        timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    priceSeries = priceChart.addLineSeries({
        color: '#3b82f6', lineWidth: 2,
        priceFormat: { type: 'price', precision: 0, minMove: 1 },
        lastValueVisible: true, priceLineColor: '#3b82f6',
    });

    // 2. LightweightCharts — Signal Intelligence (linked to priceChart)
    const signalContainer = document.getElementById('signalChart');
    signalChart = LightweightCharts.createChart(signalContainer, {
        width: signalContainer.clientWidth,
        height: 120,
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#71717a' },
        grid: { vertLines: { display: false }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
        rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)', scaleMargins: { top: 0.1, bottom: 0.1 } },
        timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false, visible: false },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    buySeries = signalChart.addHistogramSeries({ color: 'rgba(34,197,94,0.6)', priceFormat: { type: 'volume' } });
    sellSeries = signalChart.addHistogramSeries({ color: 'rgba(239,68,68,0.6)', priceFormat: { type: 'volume' } });

    // ── SYNC LOGIC ──
    let isSyncing = false;
    const sync = (src, dest) => {
        src.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (isSyncing) return;
            isSyncing = true;
            dest.timeScale().setVisibleLogicalRange(range);
            isSyncing = false;
        });
    };
    sync(priceChart, signalChart);
    sync(signalChart, priceChart);

    new ResizeObserver(() => {
        const w = container.clientWidth, hh = +container.style.height.replace('px', '');
        const sw = signalContainer.clientWidth;
        if (w > 0 && hh > 0) priceChart.applyOptions({ width: w, height: hh });
        if (sw > 0) signalChart.applyOptions({ width: sw });
    }).observe(container);

    // 3. Chart.js — Trade Performance
    perfChart = new Chart(document.getElementById('perfChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Trade PnL ($)',
                data: [],
                backgroundColor: [],
                borderRadius: 4,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => `PnL: $${ctx.raw.toFixed(2)}`,
                        title: ctx => `Trade ${ctx[0].label}`
                    }
                }
            },
            scales: {
                x: { display: false },
                y: {
                    ticks: { color: '#4b5563', callback: v => `$${v}` },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    border: { color: 'rgba(255,255,255,0.06)' }
                }
            }
        }
    });

    // ChartsReady is now set after all init
    chartsReady = true;
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
const fmt = (n) => n >= 0
    ? `+$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : `-$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtPct = (n) => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const el = (id) => document.getElementById(id);

function setClass(elem, cls) {
    elem.className = elem.className.replace(/\b(positive|negative|neutral|warn)\b/g, '');
    if (cls) elem.classList.add(cls);
}

function flashUpdate(elem) {
    elem.classList.remove('flash-update');
    void elem.offsetWidth;
    elem.classList.add('flash-update');
}

// ── WARMUP PROGRESS BAR ───────────────────────────────────────────────────────
async function updateWarmup() {
    try {
        const res = await fetch(`${API}/warmup`);
        const d = await res.json();
        const bar = el('warmup-bar');
        const label = el('warmup-label');
        const wrap = el('warmup-wrap');
        if (!wrap) return;

        if (d.done) {
            warmupDone = true;
            wrap.style.display = 'none';
            return;
        }
        warmupDone = false;
        wrap.style.display = 'flex';
        bar.style.width = d.pct + '%';
        const secs = d.seconds_remaining;
        if (d.stalled) {
            label.textContent = `Waiting for live feed… ${d.ticks}/${d.min_ticks} ticks`;
        } else {
            label.textContent = `Warming up… ${d.ticks}/${d.min_ticks} ticks · ~${secs}s remaining`;
        }
    } catch (e) { }
}

// ── FRESH START DETECTION ─────────────────────────────────────────────────────
// Use localStorage so that browser refreshes do NOT count as a new session.
// Only a true system restart (new SERVER_START value) triggers a full UI reset.
async function checkFreshStart() {
    try {
        const res = await fetch(`${API}/session_start`);
        const data = await res.json();
        const stored = localStorage.getItem('tradingSessionStart');

        if (!stored) {
            localStorage.setItem('tradingSessionStart', data.session_start);
            localStorage.setItem('tradingSessionStartMs', data.session_start_ms);
            knownSessionStart = data.session_start;
            startTime = data.session_start_ms;
            return;
        }

        knownSessionStart = stored;
        startTime = parseInt(localStorage.getItem('tradingSessionStartMs') || data.session_start_ms);

        if (data.session_start !== stored) {
            console.log('[Dashboard] System restarted — resetting UI...');
            localStorage.setItem('tradingSessionStart', data.session_start);
            localStorage.setItem('tradingSessionStartMs', data.session_start_ms);
            knownSessionStart = data.session_start;
            startTime = data.session_start_ms;
            lastTradeCount = 0;
            lastLogLength = 0;
            warmupDone = false;
            if (chartsReady) {
                priceSeries.setData([]);
                priceSeries.setMarkers([]);
                perfChart.data.labels = [];
                perfChart.data.datasets[0].data = [];
                perfChart.data.datasets[0].backgroundColor = [];
                perfChart.update();
                buySeries.setData([]);
                sellSeries.setData([]);
            }
            el('trades-list').innerHTML = '<div class="empty-state">New session — no trades yet</div>';
            el('lessons-log').innerHTML = '';
            el('intent-display').textContent = 'New session starting...';
            el('balance-val').textContent = '$1,250';
            el('total-profit-val').textContent = '+$0.00';
            el('win-rate-val').textContent = '--%';
            el('trades-count-val').textContent = '0';
            el('missed-count-val').textContent = '0';
            el('llm-cost-val').textContent = '$0.0000';
            el('llm-cpt-val').textContent = '—';
            el('llm-cpp-val').textContent = '—';
            el('llm-conv-val').textContent = '0.0%';
        }
        // else: same session, browser refresh — do nothing, charts will refill from API
    } catch (e) { }
}

// ── UPTIME ────────────────────────────────────────────────────────────────────
function updateUptime() {
    const s = Math.floor((Date.now() - startTime) / 1000);
    const hh = String(Math.floor(s / 3600)).padStart(2, '0');
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    el('uptime-val').textContent = `${hh}:${mm}:${ss}`;
}

// ── PRICE CHART ── always renders from DB prices, independent of trades ────────
async function updatePriceChart() {
    try {
        const res = await fetch(`${API}/market/history?symbol=BTCUSDT`);
        const data = await res.json();
        if (!chartsReady) return;

        // Always try to plot whatever ticks we have (even during warmup)
        if (data.length > 0) {
            const series = data
                .map(d => ({
                    time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                    value: d.price
                }))
                .filter(d => d.time > 0)
                .sort((a, b) => a.time - b.time);

            // Keep only the last unique timestamp per second
            const byTime = new Map();
            for (const pt of series) byTime.set(pt.time, pt);
            const unique = Array.from(byTime.values());

            if (unique.length > 0) priceSeries.setData(unique);
        }

        // Live price header (always update, even during warmup)
        if (data.length > 0) {
            const latest = data[data.length - 1];
            const prev = data[Math.max(0, data.length - 12)];
            const change = ((latest.price - prev.price) / prev.price) * 100;
            const priceEl = el('current-price');
            priceEl.textContent = `$${latest.price.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
            flashUpdate(priceEl);
            const changeEl = el('price-change');
            changeEl.textContent = fmtPct(change);
            changeEl.className = 'live-change ' + (change >= 0 ? 'positive' : 'negative');
        }
    } catch (e) { console.warn('price chart update failed', e); }
}

// ── PORTFOLIO SUMMARY ─────────────────────────────────────────────────────────
async function updatePortfolioSummary() {
    try {
        const res = await fetch(`${API}/portfolio/summary`);
        const d = await res.json();

        const pnlEl = el('total-profit-val');
        pnlEl.textContent = fmt(d.total_pnl);
        setClass(pnlEl, d.total_pnl >= 0 ? 'positive' : 'negative');
        flashUpdate(pnlEl);

        el('win-rate-val').textContent = d.total_trades > 0 ? d.win_rate.toFixed(1) + '%' : '--%';
        el('trades-count-val').textContent = d.total_trades;
        el('missed-count-val').textContent = d.missed_count;
        el('llm-cost-val').textContent = `$${(d.llm_cost_today ?? 0).toFixed(4)}`;
        el('llm-cpt-val').textContent = d.llm_cost_per_traded_signal != null
            ? `$${d.llm_cost_per_traded_signal.toFixed(4)}`
            : '—';
        el('llm-cpp-val').textContent = d.llm_cost_per_dollar_pnl != null
            ? `${d.llm_cost_per_dollar_pnl.toFixed(4)}x`
            : '—';
        el('llm-conv-val').textContent = `${(d.llm_trade_conversion_rate ?? 0).toFixed(1)}%`;

        const balance = 1250 + d.total_pnl;
        el('balance-val').textContent = '$' + balance.toLocaleString('en-US', { maximumFractionDigits: 2 });

        const openEl = el('open-position');
        if (d.open_position) {
            const op = d.open_position;
            openEl.textContent = `${op.side === 'LONG' ? '📈' : '📉'} ${op.side} ${op.symbol} @ $${op.entry_price?.toLocaleString('en-US', { maximumFractionDigits: 0 }) ?? '—'}`;
            openEl.className = 'open-pos-badge ' + (op.side === 'LONG' ? 'positive' : 'negative');
        } else {
            openEl.textContent = 'No open position';
            openEl.className = 'open-pos-badge neutral';
        }
    } catch (e) { console.warn('portfolio summary failed', e); }
}

// ── TRADE PERFORMANCE CHART ── Per-trade PnL bars (green/red) ────────────────
async function updatePerfChart() {
    try {
        const res = await fetch(`${API}/trades/recent`);
        const data = await res.json();
        if (!chartsReady) return;

        if (!data.length) {
            perfChart.data.labels = [];
            perfChart.data.datasets[0].data = [];
            perfChart.data.datasets[0].backgroundColor = [];
            const pnlInfoEl = el('perf-empty');
            if (pnlInfoEl) pnlInfoEl.style.display = 'flex';
            perfChart.update('none');
            return;
        }

        const pnlInfoEl = el('perf-empty');
        if (pnlInfoEl) pnlInfoEl.style.display = 'none';

        // Reverse to show oldest first (left→right)
        const trades = [...data].reverse();
        const labels = trades.map((t, i) => `#${i + 1}`);
        const pnls = trades.map(t => +(t.pnl ?? 0).toFixed(2));
        const colors = pnls.map(p => p >= 0 ? 'rgba(34,197,94,0.8)' : 'rgba(239,68,68,0.8)');

        perfChart.data.labels = labels;
        perfChart.data.datasets[0].data = pnls;
        perfChart.data.datasets[0].backgroundColor = colors;
        perfChart.update('none');

        // Session win/loss summary under chart title
        const wins = pnls.filter(p => p > 0).length;
        const sumEl = el('perf-summary');
        if (sumEl) {
            const net = pnls.reduce((a, b) => a + b, 0);
            sumEl.textContent = `${wins}W / ${pnls.length - wins}L · Net: ${fmt(net)}`;
            sumEl.className = 'perf-summary ' + (net >= 0 ? 'positive' : 'negative');
        }
    } catch (e) { }
}

// ── SIGNALS ───────────────────────────────────────────────────────────────────
async function updateSignals() {
    try {
        const res = await fetch(`${API}/signals/history?symbol=BTCUSDT&limit=60`);
        const data = await res.json();
        if (!data.length || !chartsReady) return;

        const history = data.map(d => ({
            time: Math.floor(new Date(d.timestamp).getTime() / 1000),
            buy: d.buy_votes,
            sell: d.sell_votes,
        })).sort((a, b) => a.time - b.time);

        if (history.length) {
            buySeries.setData(history.map(h => ({ time: h.time, value: h.buy })));
            sellSeries.setData(history.map(h => ({ time: h.time, value: -h.sell }))); // Negative for bottom projection
        }

        const latest = data[data.length - 1];
        if (latest) {
            el('rsi-badge').textContent = `RSI ${latest.rsi?.toFixed(1) ?? '—'}`;
            el('macd-badge').textContent = `MACD ${latest.macd ?? '—'}`;
            el('bb-badge').textContent = `BB ${latest.bb_pct?.toFixed(0) ?? '—'}%`;

            const totalVotes = Math.max(1, Number(latest.max_voters || 8));
            el('buy-bar').style.width = ((latest.buy_votes / totalVotes) * 100) + '%';
            el('sell-bar').style.width = ((latest.sell_votes / totalVotes) * 100) + '%';
            el('buy-count').textContent = `${latest.buy_votes}/${totalVotes}`;
            el('sell-count').textContent = `${latest.sell_votes}/${totalVotes}`;
            el('rsi-val').textContent = latest.rsi?.toFixed(1) ?? '—';
            el('macd-val').textContent = latest.macd ?? '—';
            el('bb-val').textContent = latest.bb_pct?.toFixed(0) + '%' ?? '—';
            el('outcome-val').textContent = latest.outcome ?? '—';

            const outcomeEl = el('outcome-val');
            if (latest.outcome === 'TRADED') setClass(outcomeEl, 'positive');
            else if (latest.outcome === 'MISSED') setClass(outcomeEl, 'warn');
            else setClass(outcomeEl, 'neutral');
        }

        // ── Trade markers on price chart — one marker per unique second, no overlaps ─
        const traded = data.filter(d => d.outcome === 'TRADED');
        const missed = data.filter(d => d.outcome === 'MISSED');

        // Build a Map keyed by second-timestamp → keep last entry per second
        const markerMap = new Map();
        for (const d of missed) {
            const t = Math.floor(new Date(d.timestamp).getTime() / 1000);
            if (t > 0) markerMap.set(t, {
                time: t,
                position: 'aboveBar', color: '#f59e0b', shape: 'circle', text: 'MISSED',
            });
        }
        // Traded overwrites missed if on same second (traded is higher priority)
        for (const d of traded) {
            const t = Math.floor(new Date(d.timestamp).getTime() / 1000);
            if (t > 0) markerMap.set(t, {
                time: t,
                position: d.claude_action === 'LONG' ? 'belowBar' : 'aboveBar',
                color: '#22c55e', shape: d.claude_action === 'LONG' ? 'arrowUp' : 'arrowDown',
                text: `${d.claude_action} ${((d.claude_conf ?? 0) * 100).toFixed(0)}%`,
            });
        }

        const uniqueMarkers = Array.from(markerMap.values()).sort((a, b) => a.time - b.time);
        if (priceSeries) priceSeries.setMarkers(uniqueMarkers);

    } catch (e) { console.warn('signals update failed', e); }
}

// ── TRADES TABLE ──────────────────────────────────────────────────────────────
async function updateTrades() {
    try {
        const res = await fetch(`${API}/trades/recent`);
        const data = await res.json();
        if (!data.length) {
            el('trades-list').innerHTML = '<div class="empty-state">No trades yet this session</div>';
            return;
        }
        const closed = data.filter(t => t.status === 'CLOSED');
        if (closed.length > lastTradeCount) flashUpdate(el('trades-list'));
        lastTradeCount = closed.length;

        const rows = data.slice(0, 15).map(t => {
            const pnl = t.pnl ?? 0;
            const cls = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : 'neutral';
            const sideIcon = t.side === 'LONG' ? '↑' : '↓';
            const time = t.entry_time ? t.entry_time.slice(11, 16) : '--:--';
            return `<div class="trade-row ${cls}">
                <span class="trade-side ${t.side === 'LONG' ? 'buy' : 'sell'}">${sideIcon} ${t.side}</span>
                <span class="trade-price">$${(t.price || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
                <span class="trade-pnl ${cls}">${pnl !== 0 ? fmt(pnl) : t.status}</span>
                <span class="trade-time">${time}</span>
            </div>`;
        }).join('');
        el('trades-list').innerHTML = rows;
    } catch (e) { }
}

// ── LESSONS ───────────────────────────────────────────────────────────────────
async function updateLessons() {
    try {
        const res = await fetch(`${API}/lessons`);
        const data = await res.json();
        if (!data.length) {
            el('lessons-log').innerHTML = '<div class="empty-state">No lessons yet</div>';
            return;
        }
        const html = data.map(l => {
            const icon = l.severity === 'GOLDEN' ? '🏆' : l.severity === 'WIN' ? '✅' : '❌';
            const cls = l.severity === 'GOLDEN' ? 'lesson-gold' : l.severity === 'WIN' ? 'lesson-win' : 'lesson-loss';
            return `<div class="lesson-row ${cls}">
                <span class="lesson-icon">${icon}</span>
                <span class="lesson-text"><b>${l.condition}</b> → ${l.lesson}</span>
            </div>`;
        }).join('');
        el('lessons-log').innerHTML = html;
    } catch (e) { }
}

// ── INTENT ────────────────────────────────────────────────────────────────────
async function updateIntent() {
    try {
        const res = await fetch(`${API}/intent`);
        const data = await res.json();
        const intentEl = el('intent-display');
        const header = data.beginner_message || data.message || 'Scanning markets...';
        const lines = Array.isArray(data.status_lines) ? data.status_lines : [];
        const details = lines.length ? `\n${lines.map(s => `• ${s}`).join('\n')}` : '';
        const rendered = `${header}${details}`;
        if (rendered !== intentEl.textContent) {
            intentEl.textContent = rendered;
            flashUpdate(intentEl);
        }
    } catch (e) { }
}

// ── REGIME ────────────────────────────────────────────────────────────────────
async function updateRegime() {
    try {
        const res = await fetch(`${API}/regime`);
        const d = await res.json();

        const regimeEl = el('regime-badge');
        const regimeVerdict = el('regime-verdict');
        const atrEl = el('atr-verdict');
        const sessEl = el('session-badge');
        const sessVerdict = el('session-verdict');
        if (!regimeEl) return;

        const rMap = { BULL: 'regime-bull', BEAR: 'regime-bear', CHOPPY: 'regime-choppy', NEUTRAL: 'regime-neutral', UNKNOWN: 'regime-neutral', WARMING_UP: 'regime-neutral', ERROR: 'regime-neutral' };
        regimeEl.textContent = d.regime || 'WARMING';
        regimeEl.className = 'regime-badge ' + (rMap[d.regime] || 'regime-neutral');
        if (regimeVerdict) regimeVerdict.textContent = d.verdict || '';
        if (atrEl && d.atr_verdict) atrEl.textContent = d.atr_verdict;

        const sMap = { PREMIUM: 'sess-premium', HIGH: 'sess-high', MODERATE: 'sess-moderate', LOW: 'sess-low' };
        if (sessEl) { sessEl.textContent = d.session || '—'; sessEl.className = 'sess-badge ' + (sMap[d.session_quality] || 'sess-low'); }
        if (sessVerdict && d.session_verdict) sessVerdict.textContent = d.session_verdict;
    } catch (e) { }
}

// ── LOGS ──────────────────────────────────────────────────────────────────────
async function updateLogs() {
    try {
        const res = await fetch(`${API}/logs?lines=60`);
        const data = await res.json();
        if (!data.logs) return;
        const logEl = el('log-terminal');
        const content = data.logs.join('').trim();
        if (content !== logEl.dataset.last) {
            logEl.textContent = content;
            logEl.dataset.last = content;
            logEl.scrollTop = logEl.scrollHeight;
            flashUpdate(logEl);
        }
    } catch (e) { }
}

// ── MASTER POLL ───────────────────────────────────────────────────────────────
async function pollAll() {
    await checkFreshStart();
    const results = await Promise.allSettled([
        updateWarmup(),
        updatePriceChart(),
        updatePortfolioSummary(),
        updateIntent(),
        updateSignals(),
        updateRegime(),
    ]);
    const hasFailure = results.some(r => r.status === 'rejected');
    if (hasFailure) {
        const intentEl = el('intent-display');
        if (intentEl && !intentEl.textContent.includes('disconnected')) {
            intentEl.textContent = 'Dashboard disconnected from backend. Retrying...';
            flashUpdate(intentEl);
        }
    }
}

async function pollSlow() {
    await Promise.allSettled([
        updatePerfChart(),
        updateTrades(),
        updateLessons(),
        updateLogs(),
    ]);
}

// ── RESIZER LOGIC ─────────────────────────────────────────────────────────────
function initResizer() {
    const resizer = el('v-resizer');
    const aside = document.querySelector('.ai-panel');
    let isResizing = false;

    // Load saved width
    const savedWidth = localStorage.getItem('ai-panel-width');
    if (savedWidth) aside.style.width = savedWidth + 'px';

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const width = window.innerWidth - e.clientX - 12; // 12px padding offset
        if (width > 150 && width < 600) {
            aside.style.width = width + 'px';
            localStorage.setItem('ai-panel-width', width);
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = 'default';
        }
    });
}

// ── BOOT ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    initCharts();
    initResizer();
    setInterval(updateUptime, 1000);

    await pollAll();
    await pollSlow();

    setInterval(pollAll, 3000);
    setInterval(pollSlow, 8000);
});

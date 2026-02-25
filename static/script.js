/* ════════════════════════════════════════════════════════════════════════════
   Crypto AI Trading Terminal — script.js  (Engine v6 Dynamic Dashboard)
   Polls every 3 seconds, detects session restarts, shows regime/ATR/session
   ════════════════════════════════════════════════════════════════════════════ */

const API = "/api";
let priceChart = null, priceSeries = null;
let equityChart = null, signalChart = null;
let chartsReady = false;
let startTime = Date.now();
let knownSessionStart = null;   // for fresh-start detection
let lastLogLength = 0;
let lastTradeCount = 0;

// ── INIT ──────────────────────────────────────────────────────────────────────
function initCharts() {
    // 1. LightweightCharts — Price
    const container = document.getElementById('priceChart');
    const h = container.parentElement.clientHeight - 56;
    container.style.height = Math.max(h, 220) + 'px';

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

    new ResizeObserver(() => {
        const w = container.clientWidth, hh = +container.style.height.replace('px', '');
        if (w > 0 && hh > 0) priceChart.applyOptions({ width: w, height: hh });
    }).observe(container);

    // 2. Chart.js — Equity Curve
    equityChart = new Chart(document.getElementById('equityChart').getContext('2d'), {
        type: 'line',
        data: {
            labels: [], datasets: [{
                data: [], borderColor: '#22c55e', borderWidth: 2,
                pointRadius: 0, tension: 0.4, fill: true,
                backgroundColor: 'rgba(34,197,94,0.07)'
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { display: false }, y: { display: false } },
            animation: false
        }
    });

    // 3. Chart.js — Signal Intelligence
    signalChart = new Chart(document.getElementById('signalChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels: [],
            datasets: [
                { label: 'BUY votes', data: [], backgroundColor: 'rgba(34,197,94,0.75)', borderRadius: 3, barPercentage: 0.7 },
                { label: 'SELL votes', data: [], backgroundColor: 'rgba(239,68,68,0.75)', borderRadius: 3, barPercentage: 0.7 },
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { display: false },
                y: { min: 0, max: 5, ticks: { color: '#4b5563', stepSize: 1 }, grid: { color: 'rgba(255,255,255,0.04)' } }
            }
        }
    });

    chartsReady = true;
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
const fmt = (n) => n >= 0
    ? `+$${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : `-$${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

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

// ── FRESH START DETECTION ─────────────────────────────────────────────────────
async function checkFreshStart() {
    try {
        const res = await fetch(`${API}/session_start`);
        const data = await res.json();
        if (!knownSessionStart) {
            knownSessionStart = data.session_start;
            startTime = Date.now();
            return;
        }
        if (data.session_start !== knownSessionStart) {
            // New session detected — reset local state
            console.log('[Dashboard] New session detected, refreshing UI...');
            knownSessionStart = data.session_start;
            startTime = Date.now();
            lastTradeCount = 0;
            lastLogLength = 0;
            // Clear charts
            if (chartsReady) {
                priceSeries.setData([]);
                equityChart.data.labels = [];
                equityChart.data.datasets[0].data = [];
                equityChart.update();
                signalChart.data.labels = [];
                signalChart.data.datasets[0].data = [];
                signalChart.data.datasets[1].data = [];
                signalChart.update();
            }
            el('trades-list').innerHTML = '<div class="empty-state">New session — no trades yet</div>';
            el('lessons-log').innerHTML = '';
            el('intent-display').textContent = 'New session starting...';
            el('balance-val').textContent = '$1,00,000';
            el('total-profit-val').textContent = '+$0.00';
            el('win-rate-val').textContent = '--%';
            el('trades-count-val').textContent = '0';
            el('missed-count-val').textContent = '0';
        }
    } catch (e) { /* backend not yet ready */ }
}

// ── UPTIME ────────────────────────────────────────────────────────────────────
function updateUptime() {
    const s = Math.floor((Date.now() - startTime) / 1000);
    const hh = String(Math.floor(s / 3600)).padStart(2, '0');
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    el('uptime-val').textContent = `${hh}:${mm}:${ss}`;
}

// ── PRICE CHART ───────────────────────────────────────────────────────────────
async function updatePriceChart() {
    try {
        const res = await fetch(`${API}/market/history?symbol=BTCUSDT`);
        const data = await res.json();
        if (!data.length || !chartsReady) return;

        const series = data.map(d => ({
            time: Math.floor(new Date(d.timestamp).getTime() / 1000),
            value: d.price
        })).filter(d => d.time > 0).sort((a, b) => a.time - b.time);

        // Deduplicate by time
        const seen = new Set(), unique = [];
        for (const pt of series) { if (!seen.has(pt.time)) { seen.add(pt.time); unique.push(pt); } }

        if (unique.length > 1) priceSeries.setData(unique);

        // Live price header
        const latest = data[data.length - 1];
        const prev = data[Math.max(0, data.length - 12)]; // ~60s ago
        const change = ((latest.price - prev.price) / prev.price) * 100;
        const priceEl = el('current-price');
        priceEl.textContent = `$${latest.price.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
        flashUpdate(priceEl);
        const changeEl = el('price-change');
        changeEl.textContent = fmtPct(change);
        changeEl.className = 'live-change ' + (change >= 0 ? 'positive' : 'negative');
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

        el('win-rate-val').textContent = d.win_rate.toFixed(1) + '%';
        el('trades-count-val').textContent = d.total_trades;
        el('missed-count-val').textContent = d.missed_count;

        // Approximate balance (start $1L + total_pnl)
        const balance = 100000 + d.total_pnl;
        el('balance-val').textContent = '$' + balance.toLocaleString('en-IN', { maximumFractionDigits: 0 });

        // Open position indicator
        const openEl = el('open-position');
        if (d.open_position) {
            const op = d.open_position;
            openEl.textContent = `📈 ${op.side} ${op.symbol} @ $${op.entry_price?.toLocaleString('en-IN', { maximumFractionDigits: 0 }) ?? '—'}`;
            openEl.className = 'open-pos-badge ' + (op.side === 'LONG' ? 'positive' : 'negative');
        } else {
            openEl.textContent = 'No open position';
            openEl.className = 'open-pos-badge neutral';
        }
    } catch (e) { console.warn('portfolio summary failed', e); }
}

// ── EQUITY CURVE ──────────────────────────────────────────────────────────────
async function updateEquityCurve() {
    try {
        const res = await fetch(`${API}/portfolio/history`);
        const data = await res.json();
        if (!data.length || !chartsReady) return;

        const labels = data.map(d => d.timestamp.slice(11, 16));
        const values = data.map(d => d.balance);
        equityChart.data.labels = labels;
        equityChart.data.datasets[0].data = values;
        equityChart.update('none');
    } catch (e) { }
}

// ── SIGNALS ───────────────────────────────────────────────────────────────────
async function updateSignals() {
    try {
        const res = await fetch(`${API}/signals/history?symbol=BTCUSDT&limit=60`);
        const data = await res.json();
        if (!data.length || !chartsReady) return;

        const labels = data.map(d => d.timestamp.slice(11, 16));
        const buy = data.map(d => d.buy_votes);
        const sell = data.map(d => d.sell_votes);
        signalChart.data.labels = labels;
        signalChart.data.datasets[0].data = buy;
        signalChart.data.datasets[1].data = sell;
        signalChart.update('none');

        // RSI/MACD/BB badges from latest datapoint
        const latest = data[data.length - 1];
        if (latest) {
            el('rsi-badge').textContent = `RSI ${latest.rsi?.toFixed(1) ?? '—'}`;
            el('macd-badge').textContent = `MACD ${latest.macd ?? '—'}`;
            el('bb-badge').textContent = `BB ${latest.bb_pct?.toFixed(0) ?? '—'}%`;

            // Vote tally
            const totalVotes = 5;
            const buyPct = (latest.buy_votes / totalVotes) * 100;
            const sellPct = (latest.sell_votes / totalVotes) * 100;
            el('buy-bar').style.width = buyPct + '%';
            el('sell-bar').style.width = sellPct + '%';
            el('buy-count').textContent = `${latest.buy_votes}/5`;
            el('sell-count').textContent = `${latest.sell_votes}/5`;
            el('rsi-val').textContent = latest.rsi?.toFixed(1) ?? '—';
            el('macd-val').textContent = latest.macd ?? '—';
            el('bb-val').textContent = latest.bb_pct?.toFixed(0) + '%' ?? '—';
            el('outcome-val').textContent = latest.outcome ?? '—';

            const outcomeEl = el('outcome-val');
            if (latest.outcome === 'TRADED') setClass(outcomeEl, 'positive');
            else if (latest.outcome === 'MISSED') setClass(outcomeEl, 'warn');
            else setClass(outcomeEl, 'neutral');
        }

        // Trade markers on price chart
        const traded = data.filter(d => d.outcome === 'TRADED');
        const missed = data.filter(d => d.outcome === 'MISSED');
        try {
            const markers = [
                ...traded.map(d => ({
                    time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                    position: d.claude_action === 'LONG' ? 'belowBar' : 'aboveBar',
                    color: '#22c55e', shape: d.claude_action === 'LONG' ? 'arrowUp' : 'arrowDown',
                    text: `TRADE ${d.claude_action} (${(d.claude_conf * 100).toFixed(0)}%)`,
                })),
                ...missed.map(d => ({
                    time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                    position: 'belowBar', color: '#f59e0b', shape: 'circle',
                    text: `MISSED`,
                })),
            ].filter(m => m.time > 0).sort((a, b) => a.time - b.time);

            // Deduplicate by time
            const seenT = new Set(), uniqueM = [];
            for (const m of markers) { if (!seenT.has(m.time)) { seenT.add(m.time); uniqueM.push(m); } }
            if (priceSeries) priceSeries.setMarkers(uniqueM);
        } catch (e) { }

    } catch (e) { console.warn('signals update failed', e); }
}

// ── TRADES TABLE ──────────────────────────────────────────────────────────────
async function updateTrades() {
    try {
        const res = await fetch(`${API}/trades/recent`);
        const data = await res.json();
        if (!data.length) {
            el('trades-list').innerHTML = '<div class="empty-state">No trades yet</div>';
            return;
        }

        // Flash if new trade appeared
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
                <span class="trade-price">$${(t.price || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
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
        if (data.message !== intentEl.textContent) {
            intentEl.textContent = data.message;
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

        // Regime badge
        const rMap = { BULL: 'regime-bull', BEAR: 'regime-bear', CHOPPY: 'regime-choppy', NEUTRAL: 'regime-neutral', UNKNOWN: 'regime-neutral', WARMING_UP: 'regime-neutral', ERROR: 'regime-neutral' };
        regimeEl.textContent = d.regime || 'WARMING';
        regimeEl.className = 'regime-badge ' + (rMap[d.regime] || 'regime-neutral');
        if (regimeVerdict) regimeVerdict.textContent = d.verdict || '';

        // ATR
        if (atrEl && d.atr_verdict) {
            atrEl.textContent = d.atr_verdict;
        }

        // Session
        const sMap = { PREMIUM: 'sess-premium', HIGH: 'sess-high', MODERATE: 'sess-moderate', LOW: 'sess-low' };
        if (sessEl) {
            sessEl.textContent = d.session || '—';
            sessEl.className = 'sess-badge ' + (sMap[d.session_quality] || 'sess-low');
        }
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
            // Auto-scroll to bottom
            logEl.scrollTop = logEl.scrollHeight;
            flashUpdate(logEl);
        }
    } catch (e) { }
}

// ── MASTER POLL ───────────────────────────────────────────────────────────────
async function pollAll() {
    await checkFreshStart();
    await Promise.allSettled([
        updatePriceChart(),
        updatePortfolioSummary(),
        updateIntent(),
        updateSignals(),
        updateRegime(),
    ]);
}

async function pollSlow() {
    await Promise.allSettled([
        updateEquityCurve(),
        updateTrades(),
        updateLessons(),
        updateLogs(),
    ]);
}

// ── BOOT ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    initCharts();
    setInterval(updateUptime, 1000);

    // First paint
    await pollAll();
    await pollSlow();

    // Fast cycle: price, intent, signals, regime every 3 seconds
    setInterval(pollAll, 3000);

    // Slower cycle: trades, equity, lessons, logs every 8 seconds
    setInterval(pollSlow, 8000);
});

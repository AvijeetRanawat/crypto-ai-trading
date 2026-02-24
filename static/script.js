const API = "/api";
let priceChart = null;
let priceSeries = null;
let equityChart = null;
let signalChart = null;
let chartsReady = false;
let startTime = Date.now();

// ── INIT ─────────────────────────────────────────────────────────
function initCharts() {
    // 1. LightweightCharts — Price
    const container = document.getElementById('priceChart');
    const h = container.parentElement.clientHeight - 56;
    container.style.height = Math.max(h, 200) + 'px';

    priceChart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight,
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#71717a' },
        grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
        rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
        timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    priceSeries = priceChart.addLineSeries({
        color: '#3b82f6', lineWidth: 2,
        priceFormat: { type: 'price', precision: 0, minMove: 1 },
        lastValueVisible: true,
        priceLineColor: '#3b82f6',
    });

    new ResizeObserver(() => {
        const w = container.clientWidth, hh = container.clientHeight;
        if (w > 0 && hh > 0) priceChart.applyOptions({ width: w, height: hh });
    }).observe(container);

    // 2. Chart.js — Equity
    equityChart = new Chart(
        document.getElementById('equityChart').getContext('2d'),
        {
            type: 'line',
            data: {
                labels: [], datasets: [{
                    data: [], borderColor: '#22c55e', borderWidth: 2,
                    pointRadius: 0, tension: 0.4, fill: true, backgroundColor: 'rgba(34,197,94,0.07)'
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: false } }, animation: false
            }
        }
    );

    // 3. Chart.js — Signal Intelligence bar chart
    signalChart = new Chart(
        document.getElementById('signalChart').getContext('2d'),
        {
            type: 'bar',
            data: {
                labels: [],
                datasets: [
                    { label: 'BUY votes', data: [], backgroundColor: 'rgba(34,197,94,0.7)', borderRadius: 2, barPercentage: 0.7 },
                    { label: 'SELL votes', data: [], backgroundColor: 'rgba(239,68,68,0.7)', borderRadius: 2, barPercentage: 0.7 },
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: {
                    legend: { display: false }, tooltip: {
                        callbacks: {
                            title: (items) => {
                                const ds = items[0]?.dataset?.label;
                                return `${ds} @ ${items[0]?.label}`;
                            }
                        }
                    }
                },
                scales: {
                    x: { display: false, stacked: false },
                    y: {
                        display: true, min: 0, max: 5, ticks: { color: '#71717a', font: { size: 9 }, stepSize: 1 },
                        grid: { color: 'rgba(255,255,255,0.03)' }
                    }
                }
            }
        }
    );

    chartsReady = true;
}

// ── HELPERS ───────────────────────────────────────────────────────
function dedup(series) {
    const seen = new Set();
    return series.filter(p => { if (seen.has(p.time)) return false; seen.add(p.time); return true; });
}

function formatINR(n) {
    return n.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

// ── MAIN UPDATE ───────────────────────────────────────────────────
async function updateDashboard() {
    if (!chartsReady) return;

    try {
        // ── 1. Price chart ──────────────────────────────────────────
        const histRes = await fetch(`${API}/market/history?symbol=BTCINR`);
        const histData = await histRes.json();

        if (histData.length > 1) {
            const series = histData.map(d => ({
                time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                value: d.price,
            }));
            priceSeries.setData(dedup(series));

            const latest = histData[histData.length - 1];
            const prev = histData[Math.max(0, histData.length - 2)];
            const pct = ((latest.price - prev.price) / prev.price * 100).toFixed(3);
            document.getElementById('current-price').textContent = `₹${formatINR(latest.price)}`;
            const changeEl = document.getElementById('price-change');
            changeEl.textContent = `${pct >= 0 ? '+' : ''}${pct}%`;
            changeEl.className = `live-change ${pct >= 0 ? 'positive' : 'negative'}`;
        }

        // ── 2. Signal Intelligence ──────────────────────────────────
        const sigRes = await fetch(`${API}/signals/history?symbol=BTCINR&limit=120`);
        const sigData = await sigRes.json();

        if (sigData.length > 0) {
            const labels = sigData.map(s => s.timestamp.slice(11, 16));
            const buyVotes = sigData.map(s => s.buy_votes);
            const sellVotes = sigData.map(s => s.sell_votes);

            signalChart.data.labels = labels;
            signalChart.data.datasets[0].data = buyVotes;
            signalChart.data.datasets[1].data = sellVotes;
            signalChart.update('none');

            // Live vote tally from most recent signal event
            const latest = sigData[sigData.length - 1];
            const bv = latest.buy_votes, sv = latest.sell_votes;
            document.getElementById('buy-bar').style.width = `${(bv / 5) * 100}%`;
            document.getElementById('sell-bar').style.width = `${(sv / 5) * 100}%`;
            document.getElementById('buy-count').textContent = `${bv}/5`;
            document.getElementById('sell-count').textContent = `${sv}/5`;
            document.getElementById('rsi-val').textContent = latest.rsi?.toFixed(1) ?? '—';
            document.getElementById('rsi-val').className = `ta-val ${latest.rsi < 30 ? 'positive' : latest.rsi > 70 ? 'negative' : ''}`;
            document.getElementById('macd-val').textContent = latest.macd ?? '—';
            document.getElementById('macd-val').className = `ta-val ${latest.macd?.includes('BULL') ? 'positive' : latest.macd?.includes('BEAR') ? 'negative' : ''}`;
            document.getElementById('bb-val').textContent = latest.bb_pct ? `${latest.bb_pct.toFixed(0)}%` : '—';

            const outcomeEl = document.getElementById('outcome-val');
            const outcome = latest.outcome;
            outcomeEl.textContent = outcome;
            outcomeEl.className = `ta-val ${outcome === 'TRADED' ? 'positive' : outcome === 'MISSED' ? '' : ''}`;
            if (outcome === 'MISSED') outcomeEl.style.color = 'var(--yellow)';
            else if (outcome === 'TRADED') outcomeEl.style.color = 'var(--green)';
            else outcomeEl.style.color = 'var(--muted)';

            // TA badges in chart header
            document.getElementById('rsi-badge').textContent = `RSI ${latest.rsi?.toFixed(1) ?? '—'}`;
            document.getElementById('macd-badge').textContent = `MACD ${(latest.macd ?? '—').split('_')[0]}`;
            document.getElementById('bb-badge').textContent = `BB ${latest.bb_pct?.toFixed(0) ?? '—'}%`;

            // ── Missed opportunity counter ──
            const missedCount = sigData.filter(s => s.outcome === 'MISSED').length;
            document.getElementById('missed-count-val').textContent = missedCount;

            // ── Price chart markers: 3 types ──
            const markers = [];

            // Type 1: TRADED entries (blue triangle up/down)
            for (const s of sigData) {
                if (s.outcome === 'TRADED') {
                    const isBuy = s.claude_action === 'LONG' || s.claude_action === 'BUY';
                    markers.push({
                        time: Math.floor(new Date(s.timestamp).getTime() / 1000),
                        position: isBuy ? 'belowBar' : 'aboveBar',
                        color: '#3b82f6',                // Blue = trade entered
                        shape: isBuy ? 'arrowUp' : 'arrowDown',
                        text: `ENTRY ${s.claude_action}`,
                        size: 2,
                    });
                }
            }

            // Type 2: MISSED opportunities (yellow circle)
            for (const s of sigData) {
                if (s.outcome === 'MISSED' && Math.max(s.buy_votes, s.sell_votes) >= 3) {
                    const isBuy = s.buy_votes >= s.sell_votes;
                    markers.push({
                        time: Math.floor(new Date(s.timestamp).getTime() / 1000),
                        position: isBuy ? 'belowBar' : 'aboveBar',
                        color: '#facc15',                // Yellow = missed opportunity
                        shape: 'circle',
                        text: `MISSED (${Math.max(s.buy_votes, s.sell_votes)}/5)`,
                        size: 1,
                    });
                }
            }

            // Sort markers by time (required by LightweightCharts)
            markers.sort((a, b) => a.time - b.time);
            if (markers.length) priceSeries.setMarkers(markers);
        }

        // ── 3. Trades + Exit markers (green/red at exit) ────────────
        const tradesRes = await fetch(`${API}/trades/recent`);
        const tradesData = await tradesRes.json();

        const exitMarkers = [];
        let wins = 0, closed = 0, tradeCount = 0;
        tradesData.forEach(t => {
            tradeCount++;
            if (t.status === 'CLOSED') {
                closed++;
                if (t.pnl > 0) wins++;
                if (t.exit_time) {
                    exitMarkers.push({
                        time: Math.floor(new Date(t.exit_time).getTime() / 1000),
                        position: t.pnl >= 0 ? 'aboveBar' : 'belowBar',
                        color: t.pnl >= 0 ? '#22c55e' : '#ef4444',  // Green = profit, Red = loss
                        shape: t.pnl >= 0 ? 'arrowDown' : 'arrowUp',
                        text: `${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(0)}`,
                        size: 1,
                    });
                }
            }
        });

        // Merge entry + missed + exit markers, sort by time
        const allMarkers = [...(priceSeries.markers ? [] : []), ...exitMarkers];
        if (allMarkers.length) {
            // Combine with signal markers (re-fetch needed; instead just add exits to existing)
            const currentMarkers = priceSeries.markers?.() ?? [];
            const merged = [...currentMarkers.filter(m => !exitMarkers.find(e => e.time === m.time)), ...exitMarkers];
            merged.sort((a, b) => a.time - b.time);
        }

        document.getElementById('win-rate-val').textContent = closed ? `${Math.round((wins / closed) * 100)}%` : '--%';
        document.getElementById('trades-count-val').textContent = tradeCount;

        document.getElementById('trades-list').innerHTML = tradesData.slice(0, 5).map(t => `
            <div class="trade-row">
                <div class="t-info">
                    <span class="t-sym">${t.symbol.replace('INR', '')}</span>
                    <span class="t-side ${t.side.toLowerCase()}">${t.side} @ ₹${formatINR(t.price)}</span>
                </div>
                <span class="t-pnl ${t.pnl >= 0 ? 'positive' : 'negative'}">${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(0)}</span>
            </div>`).join('');

        // ── 4. Portfolio & Equity ──────────────────────────────────
        const portRes = await fetch(`${API}/portfolio/history`);
        const portData = await portRes.json();
        if (portData.length > 0) {
            const l = portData[0];
            const pnl = l.balance - 100000;
            document.getElementById('balance-val').textContent = `₹${formatINR(l.balance)}`;
            const pnlEl = document.getElementById('total-profit-val');
            pnlEl.textContent = `${pnl >= 0 ? '+' : ''}₹${formatINR(Math.abs(pnl))}`;
            pnlEl.className = `pill-value ${pnl >= 0 ? 'positive' : 'negative'}`;
            const hist = [...portData].reverse();
            equityChart.data.labels = hist.map(h => h.timestamp);
            equityChart.data.datasets[0].data = hist.map(h => h.balance);
            equityChart.update('none');
        }

        // ── 5. AI Intent ───────────────────────────────────────────
        const intentData = await (await fetch(`${API}/intent`)).json();
        document.getElementById('intent-display').innerHTML =
            `<span>${intentData.message}</span>` +
            (intentData.targets?.length ? `<div style="margin-top:4px;font-size:10px;color:var(--muted)">Watching: ${intentData.targets.join(', ')}</div>` : '');

        // ── 6. Lessons ─────────────────────────────────────────────
        const lessonsData = await (await fetch(`${API}/lessons`)).json();
        document.getElementById('lessons-log').innerHTML = lessonsData.map(l => `
            <div class="lesson-box ${l.severity?.toLowerCase()}">
                <div class="l-title">${l.severity} · ${(l.condition || '').slice(0, 45)}</div>
                <div class="l-body">${l.lesson}</div>
            </div>`).join('');

        // ── 7. Logs ────────────────────────────────────────────────
        const logsData = await (await fetch(`${API}/logs`)).json();
        const logEl = document.getElementById('log-terminal');
        logEl.textContent = logsData.logs.join('');
        logEl.scrollTop = logEl.scrollHeight;

        // ── 8. Uptime ──────────────────────────────────────────────
        const s = Math.floor((Date.now() - startTime) / 1000);
        document.getElementById('uptime-val').textContent =
            `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

    } catch (err) {
        console.error('Dashboard sync error:', err);
    }
}

// ── BOOT ─────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    initCharts();
    updateDashboard();
    setInterval(updateDashboard, 3000);
});

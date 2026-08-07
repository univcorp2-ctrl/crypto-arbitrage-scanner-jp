const state = { overview: null, exchanges: [], section: 'overview' };
const titles = { overview: '運用概要', assets: '資産・配分', trades: '取引履歴', exchanges: '取引所API', risk: '運用・リスク' };

const yen = value => new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 }).format(Number(value || 0));
const num = (value, digits = 2) => Number(value ?? 0).toLocaleString('ja-JP', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pct = value => `${num(value, 2)}%`;
const bps = value => `${num(value, 2)} bps`;
const time = value => value ? new Date(value).toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

async function refresh(showMessage = false) {
  try {
    const [overview, exchanges] = await Promise.all([api('/api/overview'), api('/api/exchanges')]);
    state.overview = overview;
    state.exchanges = exchanges.items || [];
    renderAll();
    if (showMessage) toast('最新データへ更新しました');
  } catch (error) {
    toast(`更新失敗: ${error.message}`, true);
  }
}

function renderAll() {
  renderStatus();
  renderMetrics();
  renderCharts();
  renderOpportunities();
  renderAssets();
  renderTrades();
  renderExchanges();
  renderRisk();
  document.querySelector('#updatedAt').textContent = `更新 ${time(state.overview.generated_at)}`;
}

function renderStatus() {
  const status = state.overview.status;
  const source = document.querySelector('#sourceBadge');
  source.textContent = String(status.last_source || 'unknown').toUpperCase();
  source.className = `badge ${status.last_source?.startsWith('public') ? 'good' : 'warn'}`;
  const run = document.querySelector('#runBadge');
  run.textContent = status.running ? '稼働中' : '停止中';
  run.className = `badge ${status.running ? 'good' : 'warn'}`;
  const kill = document.querySelector('#killSwitchButton');
  kill.classList.toggle('active', status.kill_switch);
  kill.textContent = status.kill_switch ? 'Kill switch ON' : 'Kill switch';
  document.querySelector('#modeSelect').value = status.mode;
  document.querySelector('#intervalValue').textContent = `${num(status.interval_seconds, 0)} 秒`;
  document.querySelector('#lastScanValue').textContent = time(status.last_scan_at);
}

function formatMetric(key, value) {
  if (['equity_jpy', 'daily_change_jpy', 'realized_pnl_jpy', 'today_realized_pnl_jpy', 'fees_jpy', 'turnover_jpy'].includes(key)) return yen(value);
  if (['total_return_pct', 'annualized_return_pct', 'annualized_volatility_pct', 'max_drawdown_pct', 'win_rate_pct', 'fill_ratio_pct'].includes(key)) return pct(value);
  if (key === 'avg_net_bps') return bps(value);
  if (key === 'avg_latency_ms') return `${num(value, 0)} ms`;
  if (['sharpe', 'sortino', 'calmar', 'profit_factor'].includes(key)) return value == null ? '—' : num(value, 2);
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString('ja-JP') : '—';
}

function renderMetrics() {
  const metrics = state.overview.metrics || {};
  document.querySelectorAll('[data-metric]').forEach(node => {
    const key = node.dataset.metric;
    node.textContent = formatMetric(key, metrics[key]);
    node.classList.toggle('positive', Number(metrics[key]) > 0 && ['daily_change_jpy', 'realized_pnl_jpy', 'total_return_pct'].includes(key));
    node.classList.toggle('negative', Number(metrics[key]) < 0);
  });
  document.querySelectorAll('[data-detail]').forEach(node => {
    const key = node.dataset.detail;
    node.textContent = formatMetric(key, metrics[key]);
    node.classList.toggle('negative', Number(metrics[key]) < 0);
  });
  const daily = document.querySelector('[data-submetric="daily_change_jpy"]');
  daily.textContent = `日次 ${formatMetric('daily_change_jpy', metrics.daily_change_jpy)}`;
  daily.className = Number(metrics.daily_change_jpy) >= 0 ? 'positive' : 'negative';
  document.querySelector('[data-submetric="realized_pnl_jpy"]').textContent = `実現損益 ${yen(metrics.realized_pnl_jpy)}`;
  document.querySelector('[data-submetric="sortino"]').textContent = `Sortino ${formatMetric('sortino', metrics.sortino)}`;
  document.querySelector('[data-submetric="profit_factor"]').textContent = `Profit factor ${formatMetric('profit_factor', metrics.profit_factor)}`;
  document.querySelector('[data-submetric="avg_latency_ms"]').textContent = `Latency ${formatMetric('avg_latency_ms', metrics.avg_latency_ms)}`;
}

function chartSvg(series, key, color, formatter, fill = true, zeroLine = false) {
  if (!series.length) return '<div class="empty">データなし</div>';
  const width = 900, height = 250, left = 58, right = 18, top = 18, bottom = 30;
  const values = series.map(item => Number(item[key] || 0));
  let min = Math.min(...values), max = Math.max(...values);
  if (zeroLine) { min = Math.min(min, 0); max = Math.max(max, 0); }
  const range = max - min || Math.max(Math.abs(max), 1);
  min -= range * .08; max += range * .08;
  const x = index => left + index * (width - left - right) / Math.max(series.length - 1, 1);
  const y = value => top + (max - value) * (height - top - bottom) / (max - min || 1);
  const points = values.map((value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`);
  const line = `M ${points.join(' L ')}`;
  const area = `${line} L ${x(values.length - 1)},${height - bottom} L ${x(0)},${height - bottom} Z`;
  const grids = Array.from({ length: 5 }, (_, index) => {
    const gy = top + index * (height - top - bottom) / 4;
    const value = max - index * (max - min) / 4;
    return `<line class="chart-grid" x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}"/><text class="chart-axis" x="4" y="${gy + 3}">${esc(formatter(value))}</text>`;
  }).join('');
  const labels = [0, Math.floor((series.length - 1) / 2), series.length - 1].map(index => `<text class="chart-axis" x="${x(index)}" y="${height - 8}" text-anchor="middle">${esc(series[index].date)}</text>`).join('');
  const zero = zeroLine && min < 0 && max > 0 ? `<line class="chart-zero" x1="${left}" y1="${y(0)}" x2="${width - right}" y2="${y(0)}"/>` : '';
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><defs><linearGradient id="fill-${key}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>${grids}${zero}${fill ? `<path class="chart-area" d="${area}" fill="url(#fill-${key})"/>` : ''}<path class="chart-line" d="${line}" stroke="${color}"/>${labels}</svg>`;
}

function renderCharts() {
  const series = state.overview.equity || [];
  document.querySelector('#equityChart').innerHTML = chartSvg(series, 'equity_jpy', '#42e8d2', value => `${Math.round(value / 10000)}万`);
  document.querySelector('#drawdownChart').innerHTML = chartSvg(series, 'drawdown_pct', '#ff6f7e', value => `${num(value, 1)}%`, true, true);
  document.querySelector('#dailyChart').innerHTML = chartSvg(series, 'daily_pnl_jpy', '#71f5a5', value => `${Math.round(value / 1000)}k`, false, true);
  if (series.length) {
    const first = series[0], last = series[series.length - 1];
    document.querySelector('#chartFooter').innerHTML = `<span>${esc(first.date)} → ${esc(last.date)}</span><span>${series.length} 日分 / 仮想履歴を含む</span>`;
  }
}

function renderOpportunities() {
  const rows = (state.overview.opportunities || []).slice(0, 15);
  document.querySelector('#opportunityRows').innerHTML = rows.length ? rows.map(item => `<tr><td>${time(item.ts)}</td><td>${esc(item.buy_exchange)}</td><td>${esc(item.sell_exchange)}</td><td>${yen(item.buy_ask)}</td><td>${yen(item.sell_bid)}</td><td class="${Number(item.net_bps) >= 0 ? 'positive' : 'negative'}">${bps(item.net_bps)}</td><td>${yen(item.executable_notional_jpy)}</td><td>${esc(item.source)}</td></tr>`).join('') : '<tr><td colspan="8" class="empty">裁定候補なし</td></tr>';
}

function renderAssets() {
  const balances = state.overview.balances || { items: [], asset_totals: {} };
  document.querySelector('#assetSummary').innerHTML = `<div class="asset-chip"><span>合計評価額</span><strong>${yen(balances.total_equity_jpy)}</strong></div><div class="asset-chip"><span>JPY残高</span><strong>${yen(balances.asset_totals?.JPY)}</strong></div><div class="asset-chip"><span>BTC残高</span><strong>${num(balances.asset_totals?.BTC, 6)} BTC</strong></div>`;
  document.querySelector('#referencePrice').textContent = `評価基準 BTC ${yen(balances.reference_price_jpy)}`;
  document.querySelector('#balanceRows').innerHTML = (balances.items || []).map(item => `<tr><td><strong>${esc(item.exchange)}</strong></td><td>${yen(item.jpy)}</td><td>${num(item.btc, 6)}</td><td>${yen(item.btc_value_jpy)}</td><td>${yen(item.total_jpy)}</td><td>${num(item.share_pct, 1)}%</td></tr>`).join('');
  document.querySelector('#allocationBars').innerHTML = (balances.items || []).map(item => `<div class="allocation-row"><strong>${esc(item.exchange)}</strong><div class="bar-track"><div class="bar-fill" style="width:${Math.max(1, Math.min(100, Number(item.share_pct)))}%"></div></div><span>${num(item.share_pct, 1)}%</span></div>`).join('');
}

function tradeRow(item) {
  const statusClass = `status-${item.status}`;
  const pnlClass = Number(item.pnl_jpy) >= 0 ? 'positive' : 'negative';
  return `<tr><td>${time(item.ts)}</td><td class="route">${esc(item.buy_exchange)}<span class="route-arrow">→</span>${esc(item.sell_exchange)}</td><td>${num(item.quantity, 6)}</td><td>${yen(item.buy_price)}</td><td>${yen(item.sell_price)}</td><td>${bps(item.net_bps)}</td><td>${yen(item.fees_jpy)}</td><td>${num(item.latency_ms, 0)} ms</td><td class="${pnlClass}">${yen(item.pnl_jpy)}</td><td><span class="status-pill ${statusClass}">${esc(item.status)}</span></td></tr>`;
}

function renderTrades() {
  const filter = document.querySelector('#tradeFilter').value.trim().toLowerCase();
  const rows = (state.overview.trades || []).filter(item => !filter || JSON.stringify(item).toLowerCase().includes(filter));
  document.querySelector('#tradeRows').innerHTML = rows.length ? rows.map(tradeRow).join('') : '<tr><td colspan="10" class="empty">該当する取引なし</td></tr>';
}

function renderExchanges() {
  document.querySelector('#exchangeCards').innerHTML = state.exchanges.map(exchange => {
    const credentials = exchange.credentials.map(field => `<label>${esc(field.label)}<div class="credential-row"><input type="${field.secret ? 'password' : 'text'}" autocomplete="off" data-env="${esc(field.env_var)}" placeholder="ブラウザ内のみ"><code>${esc(field.env_var)}</code></div></label>`).join('');
    const notes = exchange.notes.map(note => `<li>${esc(note)}</li>`).join('');
    const status = exchange.adapter_status === 'public-live' ? '接続済み' : exchange.adapter_status === 'roadmap' ? '次期接続' : '調査中';
    return `<article class="exchange-card" data-exchange="${esc(exchange.exchange_id)}"><div class="exchange-card-head"><div><h3>${esc(exchange.display_name)}</h3><small>${esc(exchange.registered_as)} / ${esc(exchange.registration_number)}</small></div><span class="phase-pill">PHASE ${exchange.phase} · ${status}</span></div><div class="exchange-body"><div class="exchange-meta"><div><span>Public pair</span><strong>${esc(exchange.public_pair)}</strong></div><div><span>Key location</span><strong>${esc(exchange.key_location)}</strong></div></div><div class="credential-grid">${credentials}</div><div class="exchange-actions"><a class="docs-link" href="${esc(exchange.docs_url)}" target="_blank" rel="noreferrer">公式API仕様 ↗</a><button class="secondary-button" data-action="env" data-exchange="${esc(exchange.exchange_id)}">環境変数を生成</button></div><pre class="env-preview" data-preview="${esc(exchange.exchange_id)}"></pre><ul class="note-list">${notes}</ul></div></article>`;
  }).join('');
}

function renderRisk() {
  const risk = state.overview.risk || {};
  const form = document.querySelector('#riskForm');
  Object.entries(risk).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value; });
}

function toast(message, error = false) {
  const node = document.querySelector('#toast');
  node.textContent = message;
  node.style.borderColor = error ? 'rgba(255,111,126,.35)' : 'rgba(66,232,210,.25)';
  node.classList.add('show');
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => node.classList.remove('show'), 2600);
}

async function action(path, method = 'POST', payload = undefined, message = '更新しました') {
  try {
    await api(path, { method, body: payload === undefined ? undefined : JSON.stringify(payload) });
    await refresh();
    toast(message);
  } catch (error) { toast(error.message, true); }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => {
    state.section = button.dataset.section;
    document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item === button));
    document.querySelectorAll('.page-section').forEach(section => section.classList.toggle('active', section.id === `section-${state.section}`));
    document.querySelector('#pageTitle').textContent = titles[state.section];
  }));
  document.querySelector('#refreshButton').addEventListener('click', () => refresh(true));
  document.querySelector('#tickButton').addEventListener('click', () => action('/api/simulation/tick', 'POST', undefined, '1回スキャンしました'));
  document.querySelector('#startButton').addEventListener('click', () => action('/api/simulation/start', 'POST', undefined, 'シミュレーターを開始しました'));
  document.querySelector('#stopButton').addEventListener('click', () => action('/api/simulation/stop', 'POST', undefined, 'シミュレーターを停止しました'));
  document.querySelector('#resetButton').addEventListener('click', () => { if (confirm('仮想履歴と残高を初期状態へ戻しますか？')) action('/api/simulation/reset', 'POST', {}, '仮想データを初期化しました'); });
  document.querySelector('#killSwitchButton').addEventListener('click', () => action('/api/kill-switch', 'PUT', { enabled: !state.overview.status.kill_switch }, 'Kill switchを更新しました'));
  document.querySelector('#modeSelect').addEventListener('change', event => action('/api/mode', 'PUT', { mode: event.target.value }, 'データモードを変更しました'));
  document.querySelector('#tradeFilter').addEventListener('input', renderTrades);
  document.querySelector('#riskForm').addEventListener('submit', event => {
    event.preventDefault();
    const payload = Object.fromEntries([...new FormData(event.currentTarget)].map(([key, value]) => [key, Number(value)]));
    action('/api/risk', 'PUT', payload, 'リスク制限を保存しました');
  });
  document.querySelector('#exchangeCards').addEventListener('click', async event => {
    const button = event.target.closest('[data-action="env"]');
    if (!button) return;
    const card = button.closest('.exchange-card');
    const lines = [...card.querySelectorAll('[data-env]')].map(input => `${input.dataset.env}=${input.value || `<YOUR_${input.dataset.env}>`}`);
    const preview = card.querySelector('.env-preview');
    preview.textContent = lines.join('\n');
    preview.classList.add('visible');
    try { await navigator.clipboard.writeText(lines.join('\n')); toast('環境変数ブロックをコピーしました'); } catch { toast('環境変数ブロックを表示しました'); }
  });
  refresh();
  window.setInterval(refresh, 15000);
});

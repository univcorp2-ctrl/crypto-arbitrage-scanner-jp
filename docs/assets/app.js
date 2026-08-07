const DATA_URL = "data/dashboard.json";
const palette = ["#38d5e7", "#64e6a6", "#a994ff", "#ffc767", "#ff6d86", "#5aa9ff"];
const titles = {
  overview: "運用概要",
  assets: "資産・資金配置",
  trades: "取引履歴",
  performance: "パフォーマンス分析",
  exchanges: "取引所接続",
  api: "API接続設定",
  risk: "リスク・システム"
};

const yen = new Intl.NumberFormat("ja-JP", {
  style: "currency",
  currency: "JPY",
  maximumFractionDigits: 0
});
const number = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 4 });
const compact = new Intl.NumberFormat("ja-JP", { notation: "compact", maximumFractionDigits: 2 });
let dashboard = null;
let toastTimer = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtYen(value) {
  return Number.isFinite(Number(value)) ? yen.format(Number(value)) : "—";
}

function fmtNumber(value, digits = 2) {
  if (!Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("ja-JP", { maximumFractionDigits: digits });
}

function fmtPct(value, digits = 2) {
  if (!Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(digits)}%`;
}

function fmtRatio(value) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toFixed(2);
}

function tone(value) {
  return Number(value) >= 0 ? "positive" : "negative";
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

async function loadDashboard() {
  const response = await fetch(`${DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`dashboard data: HTTP ${response.status}`);
  return response.json();
}

async function refresh() {
  const button = document.getElementById("refresh-button");
  button.disabled = true;
  button.textContent = "…";
  try {
    dashboard = await loadDashboard();
    render(dashboard);
  } catch (error) {
    console.error(error);
    showToast("データを取得できませんでした。前回表示を維持します。");
    document.getElementById("health-dot").className = "health-dot degraded";
  } finally {
    button.disabled = false;
    button.textContent = "↻";
  }
}

function render(data) {
  renderHeader(data);
  renderOverview(data);
  renderAssets(data);
  renderTrades(data);
  renderPerformance(data);
  renderExchanges(data);
  renderConnectors(data);
  renderRisk(data);
}

function renderHeader(data) {
  const generated = new Date(data.generated_at);
  document.getElementById("updated-at").textContent = Number.isNaN(generated.getTime())
    ? data.generated_at
    : generated.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  const status = data.system?.run_status || "degraded";
  document.getElementById("health-dot").className = `health-dot ${status}`;
  const statusText = data.data_status === "seeded_demo_plus_live_public"
    ? "画面検証用シード履歴＋公開板スナップショット。実注文・実残高は含みません。"
    : "画面検証用の仮想シード履歴です。実績ではありません。";
  document.getElementById("data-banner-text").textContent = statusText;
}

function renderOverview(data) {
  const m = data.metrics || {};
  document.getElementById("portfolio-value").textContent = fmtYen(m.portfolio_value_jpy);
  const totalReturn = document.getElementById("portfolio-return");
  totalReturn.textContent = `${Number(m.total_return_pct || 0) >= 0 ? "+" : ""}${fmtPct(m.total_return_pct, 3)} since start`;
  totalReturn.className = `metric-change ${tone(m.total_return_pct)}`;
  setSignedValue("total-pnl", m.total_pnl_jpy, fmtYen);
  setSignedValue("today-pnl", m.today_pnl_jpy, fmtYen);
  document.getElementById("run-status").textContent = data.system?.run_status === "healthy" ? "正常" : "一部劣化";
  document.getElementById("run-status").className = data.system?.run_status === "healthy" ? "positive" : "negative";
  document.getElementById("run-reason").textContent = humanizeReason(data.system?.execution_reason);

  drawLineChart(document.getElementById("equity-chart"), data.equity_history || [], "equity_jpy", "#38d5e7", fmtYen);
  drawBarChart(document.getElementById("daily-pnl-chart"), (data.daily || []).slice(-30), "pnl_jpy");
  document.getElementById("daily-range").textContent = `${Math.min((data.daily || []).length, 30)}日`;

  const exchanges = data.exchanges || [];
  document.getElementById("venue-count").textContent = `${exchanges.filter(item => item.status === "connected").length}/${exchanges.length} connected`;
  document.getElementById("venue-health-list").innerHTML = exchanges.map(item => `
    <div class="health-row">
      <span class="status-orb ${item.status === "connected" ? "" : "degraded"}"></span>
      <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.pair || "")}</small></div>
      <div class="health-price">${fmtYen(item.bid_jpy)}<br><small>bid</small></div>
    </div>
  `).join("");

  const opportunities = data.opportunities || [];
  document.getElementById("opportunity-table-body").innerHTML = opportunities.length
    ? opportunities.slice(0, 8).map(item => `
      <tr>
        <td><div class="route"><strong>${escapeHtml(item.buy_exchange)}</strong><span class="route-arrow">→</span><strong>${escapeHtml(item.sell_exchange)}</strong></div></td>
        <td class="${tone(item.net_after_slippage_bps)}">${fmtNumber(item.net_after_slippage_bps, 2)}</td>
        <td class="${tone(item.estimated_profit_jpy)}">${fmtYen(item.estimated_profit_jpy)}</td>
        <td><span class="status-chip ${item.eligible ? "good" : "wait"}">${item.eligible ? "対象" : "監視"}</span></td>
      </tr>
    `).join("")
    : `<tr><td colspan="4">現在表示できる機会はありません。</td></tr>`;
}

function renderAssets(data) {
  const balances = data.balances || [];
  document.getElementById("balance-table-body").innerHTML = balances.map(item => `
    <tr>
      <td><strong>${escapeHtml(item.exchange)}</strong><br><small>${escapeHtml(item.fund_type)}</small></td>
      <td>${fmtYen(item.jpy)}</td>
      <td>${fmtNumber(item.btc, 8)}</td>
      <td>${fmtYen(item.btc_value_jpy)}</td>
      <td><strong>${fmtYen(item.total_jpy)}</strong></td>
      <td>${fmtPct(item.allocation_pct, 1)}</td>
      <td><span class="status-chip ${item.inventory_status === "balanced" ? "good" : "wait"}">${item.inventory_status === "balanced" ? "均衡" : "要調整"}</span></td>
    </tr>
  `).join("");
  drawAllocation(document.getElementById("allocation-chart"), balances);
  const m = data.metrics || {};
  const cards = [
    ["実現損益", fmtYen(m.realized_pnl_jpy), tone(m.realized_pnl_jpy), "ペーパーフィル累計"],
    ["在庫時価損益", fmtYen(m.unrealized_pnl_jpy), tone(m.unrealized_pnl_jpy), "BTC評価変動を含む"],
    ["累計手数料", fmtYen(m.fees_jpy), "", "取引所別仮定値"],
    ["累計スリッページ", fmtYen(m.slippage_jpy), "", "固定モデル"],
  ];
  document.getElementById("capital-breakdown").innerHTML = cards.map(([label, value, cls, sub]) => metricCard(label, value, cls, sub)).join("");
}

function renderTrades(data) {
  const trades = data.trades || [];
  document.getElementById("trade-count").textContent = `${trades.length} records`;
  document.getElementById("trade-table-body").innerHTML = trades.length
    ? trades.map(item => {
      const date = new Date(item.timestamp);
      const source = item.source === "seeded_demo" ? "DEMO" : "PUBLIC PAPER";
      return `
        <tr>
          <td>${Number.isNaN(date.getTime()) ? escapeHtml(item.timestamp) : date.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</td>
          <td><div class="route"><strong>${escapeHtml(item.buy_exchange)}</strong><span class="route-arrow">→</span><strong>${escapeHtml(item.sell_exchange)}</strong></div></td>
          <td>${fmtNumber(item.quantity_btc, 8)} BTC</td>
          <td>${fmtYen(item.buy_price_jpy)}</td>
          <td>${fmtYen(item.sell_price_jpy)}</td>
          <td class="${tone(item.net_spread_bps)}">${fmtNumber(item.net_spread_bps, 2)}</td>
          <td>${fmtYen(Number(item.fees_jpy || 0) + Number(item.slippage_cost_jpy || 0))}</td>
          <td class="${tone(item.net_pnl_jpy)}"><strong>${fmtYen(item.net_pnl_jpy)}</strong></td>
          <td><span class="status-chip ${source === "DEMO" ? "wait" : "good"}">${source}</span></td>
        </tr>`;
    }).join("")
    : `<tr><td colspan="9">取引記録はありません。</td></tr>`;
}

function renderPerformance(data) {
  const m = data.metrics || {};
  const cards = [
    ["Sharpe ratio", fmtRatio(m.sharpe_ratio), "", "年率換算・365日"],
    ["Sortino ratio", fmtRatio(m.sortino_ratio), "", "下方変動のみ"],
    ["最大DD", fmtPct(m.max_drawdown_pct, 2), "negative", "ピーク対比"],
    ["年率ボラ", fmtPct(m.annualized_volatility_pct, 2), "", "日次リターン"],
    ["勝率", fmtPct(m.win_rate_pct, 1), "", `${m.trade_count || 0} trades`],
    ["Profit factor", fmtRatio(m.profit_factor), "", "総利益 / 総損失"],
    ["平均取引損益", fmtYen(m.average_trade_pnl_jpy), tone(m.average_trade_pnl_jpy), "1アービトラージ"],
    ["Calmar ratio", fmtRatio(m.calmar_ratio), "", "年率収益 / 最大DD"],
  ];
  document.getElementById("performance-metrics").innerHTML = cards.map(([label, value, cls, sub]) => metricCard(label, value, cls, sub)).join("");
  drawLineChart(document.getElementById("drawdown-chart"), data.daily || [], "drawdown_pct", "#ff6d86", value => fmtPct(value, 2), true);
  drawBarChart(document.getElementById("performance-pnl-chart"), (data.daily || []).slice(-45), "pnl_jpy");
  document.getElementById("daily-table-body").innerHTML = [...(data.daily || [])].reverse().map(item => `
    <tr><td>${escapeHtml(item.date)}</td><td>${fmtYen(item.equity_jpy)}</td><td class="${tone(item.pnl_jpy)}">${fmtYen(item.pnl_jpy)}</td><td class="${tone(item.return_pct)}">${fmtPct(item.return_pct, 3)}</td><td class="${tone(item.drawdown_pct)}">${fmtPct(item.drawdown_pct, 3)}</td></tr>
  `).join("");
}

function renderExchanges(data) {
  const connectorMap = Object.fromEntries((data.connectors || []).map(item => [item.id, item]));
  document.getElementById("exchange-card-grid").innerHTML = (data.exchanges || []).map((item, index) => {
    const connector = connectorMap[item.id] || {};
    return `
      <article class="exchange-card">
        <div class="exchange-card-head"><div class="route"><div class="exchange-logo">${escapeHtml((item.name || "?").slice(0,1).toUpperCase())}</div><div><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(connector.priority_reason || "Public API監視")}</p></div></div><span class="priority">P${connector.priority || index + 1}</span></div>
        <div class="connector-meta"><div class="meta-box"><small>Best bid</small><code>${fmtYen(item.bid_jpy)}</code></div><div class="meta-box"><small>Best ask</small><code>${fmtYen(item.ask_jpy)}</code></div><div class="meta-box"><small>Spread</small><code>${fmtNumber(item.spread_bps, 2)} bps</code></div><div class="meta-box"><small>Public API</small><code class="${item.status === "connected" ? "positive" : "negative"}">${escapeHtml(item.status)}</code></div></div>
      </article>`;
  }).join("");
  document.getElementById("exchange-table-body").innerHTML = (data.exchanges || []).map(item => `
    <tr><td><strong>${escapeHtml(item.name)}</strong><br><small>${escapeHtml(item.pair)}</small></td><td>${fmtYen(item.bid_jpy)}</td><td>${fmtYen(item.ask_jpy)}</td><td>${fmtNumber(item.spread_bps, 2)} bps</td><td>${fmtNumber(item.taker_fee_bps, 1)} bps</td><td><span class="status-chip ${item.status === "connected" ? "good" : "bad"}">${escapeHtml(item.status)}</span></td></tr>
  `).join("");
}

function renderConnectors(data) {
  const connectors = data.connectors || [];
  document.getElementById("connector-grid").innerHTML = connectors.map(item => `
    <article class="connector-card">
      <div class="connector-head"><div><p class="eyebrow">PRIORITY ${item.priority}</p><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.priority_reason)}</p></div><span class="status-chip good">Public接続済</span></div>
      <div class="connector-meta"><div class="meta-box"><small>API key env</small><code>${escapeHtml(item.api_key_env)}</code></div><div class="meta-box"><small>API secret env</small><code>${escapeHtml(item.api_secret_env)}</code></div><div class="meta-box"><small>認証ヘッダー</small><code>${escapeHtml(item.auth_headers)}</code></div><div class="meta-box"><small>Taker仮定</small><code>${fmtNumber(item.fee_assumption_bps, 1)} bps</code></div></div>
      <div class="permission-list">${(item.recommended_permissions || []).map(value => `<span>${escapeHtml(value)}</span>`).join("")}${(item.forbidden_permissions || []).map(value => `<span class="forbidden">禁止: ${escapeHtml(value)}</span>`).join("")}</div>
      <p>保存先: ${escapeHtml(item.secret_location)} · IP制限: ${escapeHtml(item.ip_restriction)}</p>
      <p><a href="${escapeHtml(item.docs_url)}" target="_blank" rel="noopener noreferrer">公式API仕様を開く ↗</a></p>
      <div class="credential-box">
        <div class="field-grid"><div class="field"><label>API Key（一時入力）</label><input id="${item.id}-api-key" type="password" autocomplete="new-password" spellcheck="false" placeholder="この画面には保存しません"></div><div class="field"><label>API Secret（一時入力）</label><input id="${item.id}-api-secret" type="password" autocomplete="new-password" spellcheck="false" placeholder="この画面には保存しません"></div></div>
        <div class="button-row"><button class="small-button primary" type="button" data-check="${item.id}">入力形式を確認</button><button class="small-button" type="button" data-copy="${item.id}">環境変数名をコピー</button><button class="small-button" type="button" data-clear="${item.id}">消去</button></div>
        <div id="${item.id}-inline-status" class="inline-status">Private接続: 未設定 / 本番注文: ロック</div>
      </div>
    </article>
  `).join("");

  document.querySelectorAll("[data-check]").forEach(button => button.addEventListener("click", () => {
    const id = button.dataset.check;
    const key = document.getElementById(`${id}-api-key`).value.trim();
    const secret = document.getElementById(`${id}-api-secret`).value.trim();
    const status = document.getElementById(`${id}-inline-status`);
    if (!key || !secret) {
      status.textContent = "API KeyとSecretの両方を入力してください。値は送信されません。";
      status.className = "inline-status negative";
      return;
    }
    status.textContent = "入力欄を確認しました。値は送信・保存していません。実運用ではSecretストアへ登録してください。";
    status.className = "inline-status positive";
  }));
  document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
    const item = connectors.find(connector => connector.id === button.dataset.copy);
    if (!item) return;
    const template = `${item.api_key_env}=YOUR_API_KEY\n${item.api_secret_env}=YOUR_API_SECRET`;
    try {
      await navigator.clipboard.writeText(template);
      showToast(`${item.name} の環境変数テンプレートをコピーしました（実値は含みません）。`);
    } catch {
      showToast(template);
    }
  }));
  document.querySelectorAll("[data-clear]").forEach(button => button.addEventListener("click", () => {
    const id = button.dataset.clear;
    document.getElementById(`${id}-api-key`).value = "";
    document.getElementById(`${id}-api-secret`).value = "";
    document.getElementById(`${id}-inline-status`).textContent = "入力を消去しました。Private接続: 未設定";
  }));
}

function renderRisk(data) {
  const r = data.risk || {};
  const cards = [
    ["最小Net spread", `${fmtNumber(r.min_net_bps, 1)} bps`, "", "費用控除後"],
    ["最大取引額", fmtYen(r.max_trade_jpy), "", "1回あたり"],
    ["日次損失停止", fmtYen(r.daily_loss_limit_jpy), "", "実現損益基準"],
    ["Kill switch", r.kill_switch === "locked" ? "LOCKED" : r.kill_switch, "positive", "実注文無効"],
    ["片側slippage", `${fmtNumber(r.slippage_bps_per_leg, 1)} bps`, "", "固定仮定"],
    ["最大約定/Run", fmtNumber(r.max_trades_per_run, 0), "", "スケジュール毎"],
    ["Live orders", r.live_order_enabled ? "ENABLED" : "DISABLED", r.live_order_enabled ? "negative" : "positive", "コード＋設定ゲート"],
    ["Withdrawals", r.withdrawal_enabled ? "ENABLED" : "DISABLED", r.withdrawal_enabled ? "negative" : "positive", "常時禁止"],
  ];
  document.getElementById("risk-grid").innerHTML = cards.map(([label, value, cls, sub]) => metricCard(label, value, cls, sub)).join("");
  renderDefinitions(document.getElementById("system-grid"), data.system || {});
  renderDefinitions(document.getElementById("assumption-grid"), data.assumptions || {});
}

function metricCard(label, value, cls = "", sub = "") {
  return `<article class="metric-card"><div class="metric-label">${escapeHtml(label)}</div><strong class="${escapeHtml(cls)}">${escapeHtml(value)}</strong><div class="metric-sub">${escapeHtml(sub)}</div></article>`;
}

function setSignedValue(id, value, formatter) {
  const element = document.getElementById(id);
  element.textContent = `${Number(value || 0) > 0 ? "+" : ""}${formatter(value)}`;
  element.className = tone(value);
}

function humanizeReason(reason) {
  const map = {
    executed: "ペーパーフィルを記録",
    no_eligible_opportunity: "閾値以上の機会なし",
    spread_below_risk_threshold: "費用後スプレッド不足",
    insufficient_inventory: "事前配賦在庫不足",
    below_min_trade: "最小取引額未満",
    daily_loss_limit: "日次損失上限で停止",
    missing_orderbook: "板データ不足",
    insufficient_public_orderbooks: "公開板が2取引所未満",
  };
  return map[reason] || reason || "監視中";
}

function renderDefinitions(container, values) {
  container.innerHTML = Object.entries(values).map(([key, value]) => {
    const display = typeof value === "object" ? JSON.stringify(value) : String(value ?? "—");
    return `<div class="definition-row"><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(display)}</dd></div>`;
  }).join("");
}

function drawLineChart(container, rows, key, color, formatter, zeroTop = false) {
  const points = rows.map((row, index) => ({ x: index, y: Number(row[key]), label: row.timestamp || row.date })).filter(point => Number.isFinite(point.y));
  if (points.length < 2) {
    container.innerHTML = `<div class="chart-empty">表示できる系列がまだありません。</div>`;
    return;
  }
  const width = 900;
  const height = 300;
  const padding = { left: 18, right: 18, top: 24, bottom: 28 };
  const values = points.map(point => point.y);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (zeroTop) max = Math.max(max, 0);
  if (min === max) { min -= 1; max += 1; }
  const x = index => padding.left + (index / (points.length - 1)) * (width - padding.left - padding.right);
  const y = value => padding.top + ((max - value) / (max - min)) * (height - padding.top - padding.bottom);
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(point.y).toFixed(2)}`).join(" ");
  const area = `${line} L${x(points.length - 1)},${height - padding.bottom} L${x(0)},${height - padding.bottom} Z`;
  const grid = Array.from({ length: 5 }, (_, index) => {
    const gridY = padding.top + index * (height - padding.top - padding.bottom) / 4;
    return `<line x1="${padding.left}" x2="${width - padding.right}" y1="${gridY}" y2="${gridY}" stroke="rgba(148,173,195,.10)" stroke-width="1"/>`;
  }).join("");
  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="時系列チャート" preserveAspectRatio="none">
      <defs><linearGradient id="area-${key}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      ${grid}
      <path d="${area}" fill="url(#area-${key})"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="2.5" vector-effect="non-scaling-stroke"/>
      <circle cx="${x(points.length - 1)}" cy="${y(points.at(-1).y)}" r="4" fill="${color}"/>
      <text x="${padding.left}" y="15" fill="#7793a3" font-size="10">${escapeHtml(formatter(max))}</text>
      <text x="${padding.left}" y="${height - 7}" fill="#7793a3" font-size="10">${escapeHtml(formatter(min))}</text>
      <text x="${width - padding.right}" y="15" text-anchor="end" fill="${color}" font-size="12" font-weight="700">${escapeHtml(formatter(points.at(-1).y))}</text>
    </svg>`;
}

function drawBarChart(container, rows, key) {
  const values = rows.map(row => Number(row[key] || 0));
  const maxAbs = Math.max(...values.map(value => Math.abs(value)), 1);
  if (!rows.length) {
    container.innerHTML = `<div class="chart-empty">日次データがありません。</div>`;
    return;
  }
  container.innerHTML = `<div class="bar-chart">${rows.map((row, index) => {
    const value = values[index];
    const height = Math.max(Math.abs(value) / maxAbs * 46, 1.5);
    return `<div class="bar-column"><div class="bar-tooltip">${escapeHtml(row.date || "")} · ${fmtYen(value)}</div><div class="bar ${value >= 0 ? "positive" : "negative"}" style="height:${height}%"></div></div>`;
  }).join("")}</div>`;
}

function drawAllocation(container, balances) {
  if (!balances.length) {
    container.innerHTML = `<div class="chart-empty">残高データがありません。</div>`;
    return;
  }
  let cursor = 0;
  const segments = balances.map((item, index) => {
    const start = cursor;
    cursor += Number(item.allocation_pct || 0);
    return `${palette[index % palette.length]} ${start}% ${cursor}%`;
  });
  const total = balances.reduce((sum, item) => sum + Number(item.total_jpy || 0), 0);
  container.innerHTML = `<div class="donut-wrap"><div class="donut" style="background:conic-gradient(${segments.join(",")})"><div class="donut-center"><strong>${compact.format(total)}</strong><small>total JPY</small></div></div><div class="allocation-legend">${balances.map((item, index) => `<div style="--swatch:${palette[index % palette.length]}"><span>${escapeHtml(item.exchange)}</span><strong>${fmtPct(item.allocation_pct, 1)}</strong></div>`).join("")}</div></div>`;
}

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
    const view = button.dataset.view;
    document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item === button));
    document.querySelectorAll(".view").forEach(section => section.classList.toggle("active", section.id === `view-${view}`));
    document.getElementById("page-title").textContent = titles[view] || "ArbOps";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }));
  document.getElementById("refresh-button").addEventListener("click", refresh);
}

setupNavigation();
refresh();
window.setInterval(refresh, 300000);

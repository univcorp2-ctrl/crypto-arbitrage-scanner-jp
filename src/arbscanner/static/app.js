const state = { dashboard: null, selectedVenue: null, busy: false };

const pageTitles = {
  overview: "運用概要",
  assets: "資産・配分",
  trades: "取引履歴",
  connections: "取引所・API接続",
  risk: "運用設定と停止",
};

const yen = new Intl.NumberFormat("ja-JP", {
  style: "currency",
  currency: "JPY",
  maximumFractionDigits: 0,
});
const number = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 4 });

function formatYen(value) {
  return Number.isFinite(Number(value)) ? yen.format(Number(value)) : "—";
}

function formatPercent(value, digits = 2) {
  return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : "—";
}

function formatRatio(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "—";
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("ja-JP");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pnlClass(value) {
  return Number(value) >= 0 ? "positive" : "negative";
}

function setBusy(busy) {
  state.busy = busy;
  document.querySelectorAll("button").forEach((button) => {
    if (button.id === "refresh-button" || button.id === "run-once-button") {
      button.disabled = busy;
    }
  });
}

function showNotice(message, error = false) {
  const notice = document.getElementById("notice");
  notice.textContent = message;
  notice.classList.remove("hidden", "error");
  if (error) notice.classList.add("error");
  window.setTimeout(() => notice.classList.add("hidden"), 5000);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail ? JSON.stringify(payload.detail) : detail;
    } catch (_) {
      // Keep HTTP status text.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function refreshDashboard({ quiet = false } = {}) {
  if (state.busy) return;
  if (!quiet) setBusy(true);
  try {
    state.dashboard = await api("/api/dashboard");
    renderDashboard();
    document.getElementById("sync-dot").className = "status-dot online";
    document.getElementById("sync-label").textContent = state.dashboard.engine.running
      ? "ペーパー運用中"
      : "一時停止中";
  } catch (error) {
    document.getElementById("sync-dot").className = "status-dot error";
    document.getElementById("sync-label").textContent = "API接続エラー";
    if (!quiet) showNotice(`更新に失敗しました: ${error.message}`, true);
  } finally {
    if (!quiet) setBusy(false);
  }
}

function renderDashboard() {
  const data = state.dashboard;
  if (!data) return;
  const metrics = data.performance;

  setText("metric-equity", formatYen(metrics.current_equity_jpy));
  setText("metric-total-return", `累積 ${formatPercent(metrics.total_return)}`);
  setText("metric-daily-pnl", formatYen(metrics.daily_pnl_jpy), pnlClass(metrics.daily_pnl_jpy));
  setText("metric-total-pnl", formatYen(metrics.total_pnl_jpy), pnlClass(metrics.total_pnl_jpy));
  setText("metric-trade-count", `${metrics.trade_count} ペーパー約定`);
  setText("metric-sharpe", formatRatio(metrics.sharpe_ratio));
  setText("metric-drawdown", formatPercent(metrics.max_drawdown), "negative");
  setText("metric-win-rate", formatPercent(metrics.win_rate));
  setText("metric-profit-factor", `PF ${formatRatio(metrics.profit_factor)}`);
  setText("risk-sortino", formatRatio(metrics.sortino_ratio));
  setText("risk-volatility", formatPercent(metrics.annualized_volatility));
  setText("risk-fees", formatYen(metrics.fees_jpy));
  setText("risk-slippage", formatYen(metrics.slippage_jpy));
  setText("risk-reserve", formatYen(metrics.rebalance_reserve_jpy));
  setText("generated-at", `最終描画 ${formatDate(data.generated_at)}`);

  const source = data.equity.at(-1)?.data_source || "—";
  setText("equity-source", sourceLabel(source));
  setText("cycle-source", sourceLabel(data.last_cycle?.data_source || "未実行"));
  setText("engine-badge", data.engine.running ? "RUNNING" : "PAUSED");

  renderEquityChart(metrics.daily || []);
  renderPnlChart(metrics.daily || []);
  renderOpportunities(data.last_cycle?.opportunities || []);
  renderRecentTrades(data.trades.slice(0, 8));
  renderAllTrades(data.trades);
  renderAssets(data.assets);
  renderExchanges(data.exchanges);
  renderEvents(data.events);
  renderSettings(data);
}

function setText(id, text, className = "") {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = text;
  element.classList.remove("positive", "negative");
  if (className) element.classList.add(className);
}

function sourceLabel(source) {
  const labels = {
    seeded_research_demo: "初期デモ",
    live_public_orderbooks: "公開板",
    simulated_research_snapshot: "模擬板",
    none: "データなし",
  };
  return labels[source] || source;
}

function renderEquityChart(points) {
  const svg = document.getElementById("equity-chart");
  if (!points.length) {
    svg.innerHTML = '<text x="450" y="150" text-anchor="middle">データがありません</text>';
    return;
  }
  const width = 900;
  const height = 300;
  const pad = { left: 18, right: 14, top: 18, bottom: 28 };
  const values = points.map((point) => Number(point.equity_jpy));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const coordinates = values.map((value, index) => {
    const x = pad.left + (index / Math.max(values.length - 1, 1)) * (width - pad.left - pad.right);
    const y = pad.top + ((max - value) / range) * (height - pad.top - pad.bottom);
    return [x, y];
  });
  const path = coordinates.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `${path} L${coordinates.at(-1)[0]},${height - pad.bottom} L${coordinates[0][0]},${height - pad.bottom} Z`;
  const grids = [0, 0.25, 0.5, 0.75, 1].map((fraction) => {
    const y = pad.top + fraction * (height - pad.top - pad.bottom);
    const label = max - fraction * range;
    return `<line class="grid" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"/><text x="${pad.left + 2}" y="${y - 5}">${escapeHtml(yen.format(label))}</text>`;
  }).join("");
  svg.innerHTML = `
    <defs><linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#45e0c2" stop-opacity=".24"/><stop offset="100%" stop-color="#45e0c2" stop-opacity="0"/></linearGradient></defs>
    ${grids}<path class="equity-area" d="${area}"/><path class="equity-line" d="${path}"/>
    <circle cx="${coordinates.at(-1)[0]}" cy="${coordinates.at(-1)[1]}" r="4" fill="#45e0c2"/>
  `;
}

function renderPnlChart(points) {
  const svg = document.getElementById("pnl-chart");
  const values = points.slice(-20).map((point) => Number(point.daily_pnl_jpy));
  if (!values.length) {
    svg.innerHTML = '<text x="240" y="150" text-anchor="middle">データがありません</text>';
    return;
  }
  const width = 480;
  const height = 300;
  const pad = 24;
  const maxAbs = Math.max(...values.map(Math.abs), 1);
  const baseline = height / 2;
  const slot = (width - pad * 2) / values.length;
  const bars = values.map((value, index) => {
    const barHeight = Math.abs(value) / maxAbs * (height / 2 - 38);
    const x = pad + index * slot + 2;
    const y = value >= 0 ? baseline - barHeight : baseline;
    const color = value >= 0 ? "#45e0a0" : "#ff6d7a";
    return `<rect x="${x}" y="${y}" width="${Math.max(slot - 4, 2)}" height="${barHeight}" rx="2" fill="${color}" opacity=".82"><title>${escapeHtml(formatYen(value))}</title></rect>`;
  }).join("");
  svg.innerHTML = `<line class="grid" x1="${pad}" y1="${baseline}" x2="${width - pad}" y2="${baseline}"/>${bars}`;
}

function renderOpportunities(items) {
  const body = document.getElementById("opportunity-body");
  if (!items.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">現在、閾値を超える候補はありません。</td></tr>';
    return;
  }
  body.innerHTML = items.slice(0, 8).map((item) => `
    <tr>
      <td><span class="route"><b>${escapeHtml(item.buy_exchange)}</b> → ${escapeHtml(item.sell_exchange)}</span></td>
      <td>${escapeHtml(formatYen(item.buy_ask))}</td>
      <td>${escapeHtml(formatYen(item.sell_bid))}</td>
      <td class="positive">${Number(item.net_spread_bps).toFixed(2)}</td>
      <td>${Number(item.top_size).toFixed(6)}</td>
    </tr>`).join("");
}

function tradeRows(items, compact = false) {
  if (!items.length) return `<tr><td colspan="${compact ? 6 : 10}" class="empty">取引履歴がありません。</td></tr>`;
  return items.map((trade) => {
    const costs = Number(trade.fees_jpy) + Number(trade.slippage_jpy) + Number(trade.rebalance_reserve_jpy);
    if (compact) {
      return `<tr>
        <td>${escapeHtml(formatDate(trade.executed_at))}</td>
        <td><span class="route"><b>${escapeHtml(trade.buy_exchange)}</b> → ${escapeHtml(trade.sell_exchange)}</span></td>
        <td>${Number(trade.quantity_btc).toFixed(6)}</td>
        <td class="${pnlClass(trade.net_pnl_jpy)}">${escapeHtml(formatYen(trade.net_pnl_jpy))}</td>
        <td>${Number(trade.net_spread_bps).toFixed(2)}</td>
        <td><span class="source-tag">${escapeHtml(sourceLabel(trade.source))}</span></td>
      </tr>`;
    }
    return `<tr>
      <td>${escapeHtml(formatDate(trade.executed_at))}</td>
      <td>${escapeHtml(trade.buy_exchange)}</td><td>${escapeHtml(trade.sell_exchange)}</td>
      <td>${Number(trade.quantity_btc).toFixed(6)}</td>
      <td>${escapeHtml(formatYen(trade.buy_price_jpy))}</td><td>${escapeHtml(formatYen(trade.sell_price_jpy))}</td>
      <td>${escapeHtml(formatYen(trade.gross_pnl_jpy))}</td><td>${escapeHtml(formatYen(costs))}</td>
      <td class="${pnlClass(trade.net_pnl_jpy)}">${escapeHtml(formatYen(trade.net_pnl_jpy))}</td>
      <td><span class="source-tag">${escapeHtml(trade.status)}</span></td>
    </tr>`;
  }).join("");
}

function renderRecentTrades(items) {
  document.getElementById("recent-trades-body").innerHTML = tradeRows(items, true);
}

function renderAllTrades(items) {
  document.getElementById("all-trades-body").innerHTML = tradeRows(items, false);
}

function renderAssets(items) {
  const body = document.getElementById("asset-body");
  body.innerHTML = items.map((item) => `
    <tr><td><strong>${escapeHtml(item.exchange)}</strong></td>
      <td>${escapeHtml(formatYen(item.jpy))}</td><td>${Number(item.btc).toFixed(8)}</td>
      <td>${escapeHtml(formatYen(item.btc_value_jpy))}</td><td>${escapeHtml(formatYen(item.total_jpy))}</td>
      <td>${escapeHtml(formatPercent(item.allocation))}</td>
      <td class="${pnlClass(-Math.abs(item.btc_vs_equal_target))}">${Number(item.btc_vs_equal_target).toFixed(8)} BTC</td></tr>`).join("");
  document.getElementById("allocation-grid").innerHTML = items.map((item) => `
    <article class="allocation-card"><div class="allocation-top"><strong>${escapeHtml(item.exchange)}</strong><small>${escapeHtml(formatPercent(item.allocation))}</small></div>
      <div class="allocation-bar"><i style="width:${Math.min(Number(item.allocation) * 100, 100)}%"></i></div>
      <small>${escapeHtml(formatYen(item.total_jpy))}</small></article>`).join("");
}

function renderExchanges(items) {
  const grid = document.getElementById("exchange-grid");
  grid.innerHTML = items.map((venue) => {
    const connected = venue.stage === "paper_connected";
    const configured = venue.credential_status.configured;
    const status = configured ? "環境変数設定済み" : `${venue.credential_status.configured_count}/${venue.credential_status.required_count} 設定`;
    return `<article class="exchange-card ${connected ? "ready" : ""}">
      <div class="exchange-title"><h3>${escapeHtml(venue.name)}</h3><span class="stage ${connected ? "connected" : ""}">${connected ? "PAPER READY" : "NEXT"}</span></div>
      <p>${escapeHtml(venue.notes)}</p>
      <div class="env-list">${venue.credential_env.map((name) => `<code>${escapeHtml(name)}</code>`).join("")}</div>
      <p class="${configured ? "positive" : ""}">● ${escapeHtml(status)}</p>
      <div class="exchange-actions"><button class="button secondary credential-button" data-venue="${escapeHtml(venue.id)}">設定場所を見る</button><a class="button secondary" href="${escapeHtml(venue.api_docs_url)}" target="_blank" rel="noreferrer">公式仕様</a></div>
    </article>`;
  }).join("");
  grid.querySelectorAll(".credential-button").forEach((button) => {
    button.addEventListener("click", () => selectVenue(button.dataset.venue));
  });
}

function selectVenue(id) {
  state.selectedVenue = state.dashboard.exchanges.find((item) => item.id === id);
  renderCredentialForm();
  document.getElementById("credential-form").scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderCredentialForm() {
  const venue = state.selectedVenue;
  const container = document.getElementById("credential-form");
  if (!venue) return;
  const inputs = venue.credential_env.map((name, index) => `
    <label>${escapeHtml(name)}<input id="credential-${index}" type="password" autocomplete="off" spellcheck="false" placeholder="このブラウザ内だけで入力"></label>`).join("");
  container.innerHTML = `
    <div><h3>${escapeHtml(venue.name)}</h3><p class="form-note">${escapeHtml(venue.key_issuance_note)} 推奨権限: ${escapeHtml(venue.recommended_permissions.join(" / "))}。出金権限は付けません。</p></div>
    ${inputs}
    <button id="generate-env-button" class="button primary" type="button">環境変数テンプレートを生成</button>
    <textarea id="env-output" readonly placeholder="生成結果がここに表示されます"></textarea>
    <button id="copy-env-button" class="button secondary" type="button">コピー</button>
    <p class="form-note">入力値はfetch・フォーム送信・localStorageを使わず、画面内のテンプレート生成だけに利用します。サーバー側では <code>.env</code> またはSecret Managerへ登録してください。</p>`;
  document.getElementById("generate-env-button").addEventListener("click", () => {
    const lines = venue.credential_env.map((name, index) => {
      const value = document.getElementById(`credential-${index}`).value.trim();
      return `${name}=${value || "YOUR_SECRET_HERE"}`;
    });
    document.getElementById("env-output").value = lines.join("\n");
  });
  document.getElementById("copy-env-button").addEventListener("click", async () => {
    const output = document.getElementById("env-output");
    if (!output.value) return;
    try {
      await navigator.clipboard.writeText(output.value);
      showNotice("環境変数テンプレートをコピーしました。安全なSecret管理先へ貼り付けてください。");
    } catch (_) {
      output.select();
      showNotice("選択状態にしました。手動でコピーしてください。");
    }
  });
}

function renderEvents(items) {
  const list = document.getElementById("event-list");
  if (!items.length) {
    list.innerHTML = '<p class="empty">イベントはありません。</p>';
    return;
  }
  list.innerHTML = items.slice(0, 40).map((event) => `
    <div class="event-item"><time>${escapeHtml(formatDate(event.created_at))}</time><span class="event-level ${escapeHtml(event.level)}">${escapeHtml(event.level)}</span><span>${escapeHtml(event.message)}</span></div>`).join("");
}

function renderSettings(data) {
  const settings = data.engine.settings;
  setInput("setting-min-bps", settings.min_net_bps);
  setInput("setting-max-trade", settings.max_trade_jpy);
  setInput("setting-min-trade", settings.min_trade_jpy);
  setInput("setting-slippage", settings.slippage_bps);
  setInput("setting-reserve", settings.rebalance_reserve_bps);
  setInput("setting-interval", settings.interval_seconds);
  const killButton = document.getElementById("kill-button");
  killButton.textContent = data.risk.kill_switch ? "停止スイッチを解除" : "停止スイッチを有効化";
  killButton.classList.toggle("danger", !data.risk.kill_switch);
}

function setInput(id, value) {
  const input = document.getElementById(id);
  if (document.activeElement !== input) input.value = value;
}

function switchPage(page) {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === page));
  document.querySelectorAll(".page").forEach((panel) => panel.classList.toggle("active", panel.dataset.pagePanel === page));
  document.getElementById("page-title").textContent = pageTitles[page] || page;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function action(url, body = null, method = "POST") {
  if (state.busy) return;
  setBusy(true);
  try {
    const options = { method };
    if (body !== null) options.body = JSON.stringify(body);
    const result = await api(url, options);
    showNotice(result.message || "操作を反映しました。");
    await refreshDashboard({ quiet: true });
  } catch (error) {
    showNotice(`操作に失敗しました: ${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => switchPage(item.dataset.page)));
  document.querySelectorAll("[data-go-page]").forEach((item) => item.addEventListener("click", () => switchPage(item.dataset.goPage)));
  document.getElementById("refresh-button").addEventListener("click", () => refreshDashboard());
  document.getElementById("run-once-button").addEventListener("click", () => action("/api/paper/run-once"));
  document.getElementById("start-button").addEventListener("click", () => action("/api/paper/start"));
  document.getElementById("stop-button").addEventListener("click", () => action("/api/paper/stop"));
  document.getElementById("kill-button").addEventListener("click", () => {
    const enabled = !state.dashboard.risk.kill_switch;
    action("/api/risk/kill-switch", { enabled });
  });
  document.getElementById("settings-form").addEventListener("submit", (event) => {
    event.preventDefault();
    action("/api/settings/paper", {
      min_net_bps: Number(document.getElementById("setting-min-bps").value),
      max_trade_jpy: Number(document.getElementById("setting-max-trade").value),
      min_trade_jpy: Number(document.getElementById("setting-min-trade").value),
      slippage_bps: Number(document.getElementById("setting-slippage").value),
      rebalance_reserve_bps: Number(document.getElementById("setting-reserve").value),
      interval_seconds: Number(document.getElementById("setting-interval").value),
    }, "PUT");
  });
  refreshDashboard();
  window.setInterval(() => refreshDashboard({ quiet: true }), 15000);
});

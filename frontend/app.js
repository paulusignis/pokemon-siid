/**
 * Pokemon TCG ID Analyzer — Frontend
 *
 * Fetches analysis from /api/analysis and renders division-grouped pairing cards
 * showing whether each player should Intentional Draw (ID) to secure top 8.
 *
 * The API_BASE is replaced at deploy time by the CloudFront domain via sed in buildspec.
 * For local dev, set it to your API Gateway URL directly.
 */

// Replaced by buildspec.yml during deploy (see buildspec.yml comments)
const API_BASE = window.location.origin;

const DIVISION_LABELS = { MA: "Masters", SR: "Seniors", JR: "Juniors" };
const AUTO_REFRESH_MS = 5 * 60 * 1000; // 5 minutes

let autoRefreshTimer = null;

async function loadData(forceRefresh = false) {
  setLoading(true);
  setBanner("hidden");
  document.getElementById("refresh-btn").disabled = true;
  document.getElementById("rescrape-btn").disabled = true;

  try {
    const url = `${API_BASE}/api/analysis${forceRefresh ? "?force_refresh=true" : ""}`;
    const resp = await fetch(url);

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.message || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    renderData(data);

    const source = data.data_source || "unknown";
    const age = data.cache_age_seconds ?? 0;
    const ts = data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : "unknown";

    document.getElementById("cache-info").textContent =
      `Last scraped: ${ts} (${source}, ${age}s ago)`;

    if (source === "stale_cache") {
      setBanner("stale", "Live scrape failed — showing last available data.");
    }

  } catch (err) {
    console.error("Failed to load data:", err);
    setBanner("error", `Failed to load data: ${err.message}`);
    document.getElementById("divisions").innerHTML = "";
  } finally {
    setLoading(false);
    document.getElementById("refresh-btn").disabled = false;
    document.getElementById("rescrape-btn").disabled = false;
    scheduleAutoRefresh();
  }
}

function renderData(data) {
  const container = document.getElementById("divisions");
  container.innerHTML = "";

  const divisionOrder = ["MA", "SR", "JR"];
  const divisionKeys = divisionOrder.filter(d => data.divisions?.[d]);

  if (!divisionKeys.length) {
    container.innerHTML = `<p style="color:var(--text-muted);padding:2rem 0">
      No pairings found. The tournament page may not have active pairings yet.
    </p>`;
    return;
  }

  for (const divKey of divisionKeys) {
    const divData = data.divisions[divKey];
    container.appendChild(renderDivision(divKey, divData));
  }
}

function renderDivision(divKey, divData) {
  const section = document.createElement("section");
  section.className = "division";

  const label = DIVISION_LABELS[divKey] || divKey;
  const topCutBadge = divData.top_cut != null
    ? ` &bull; Top ${divData.top_cut} cut`
    : "";

  section.innerHTML = `
    <div class="division-header">
      <span class="division-name">${label}</span>
      <span class="division-badge">${divData.player_count} players${topCutBadge}</span>
    </div>
    <div class="pairings-grid" id="grid-${divKey}"></div>
  `;

  const grid = section.querySelector(`#grid-${divKey}`);
  for (const pairing of divData.current_round_pairings || []) {
    grid.appendChild(renderPairingCard(pairing));
  }

  return section;
}

function renderPairingCard(pairing) {
  const { table, name_player: np, opp_player: op, id_analysis: ia } = pairing;

  const card = document.createElement("div");

  if (!ia) {
    card.className = "pairing-card";
    card.innerHTML = `
      <div class="card-header">
        <span class="table-num">Table ${table}</span>
      </div>
      <div class="matchup">
        <div class="player-info name-side">
          <div class="player-name" title="${esc(np.name)}">${esc(np.name)}</div>
          <div class="player-record">${np.wins}-${np.losses}-${np.ties} &bull; ${np.points} pts</div>
        </div>
        <div class="vs">vs</div>
        <div class="player-info opp-side">
          <div class="player-name" title="${esc(op.name)}">${esc(op.name)}</div>
          <div class="player-record">${op.wins}-${op.losses}-${op.ties} &bull; ${op.points} pts</div>
        </div>
      </div>
    `;
    return card;
  }

  const isId = ia.recommendation === "ID";
  card.className = `pairing-card${isId ? " recommend-id" : ""}`;

  const pctId  = ((ia.prob_top_cut_if_id  ?? ia.prob_top8_if_id)  * 100).toFixed(1);
  const pctWin = ((ia.prob_top_cut_if_win ?? ia.prob_top8_if_win) * 100).toFixed(1);
  const marginPct = (ia.margin * 100).toFixed(1);
  const marginDir = ia.id_beneficial ? `ID better by ${marginPct}%` : `Win better by ${marginPct}%`;
  const topCutLabel = `Top ${ia.top_cut} probability`;

  card.innerHTML = `
    <div class="card-header">
      <span class="table-num">Table ${table}</span>
      <span class="rec-badge ${ia.recommendation}">${ia.recommendation}</span>
    </div>

    <div class="matchup">
      <div class="player-info name-side analysed-player">
        <div class="player-name" title="${esc(np.name)}">${esc(np.name)}</div>
        <div class="player-record">${np.wins}-${np.losses}-${np.ties} &bull; ${np.points} pts</div>
        <div class="analysed-label">analysed</div>
      </div>
      <div class="vs">vs</div>
      <div class="player-info opp-side">
        <div class="player-name" title="${esc(op.name)}">${esc(op.name)}</div>
        <div class="player-record">${op.wins}-${op.losses}-${op.ties} &bull; ${op.points} pts</div>
      </div>
    </div>

    <div class="prob-section">
      <div class="prob-row">
        <span class="prob-label">If Win</span>
        <div class="prob-bar-track">
          <div class="prob-bar-fill win" style="width:${pctWin}%"></div>
        </div>
        <span class="prob-pct">${pctWin}%</span>
      </div>
      <div class="prob-row">
        <span class="prob-label">If ID</span>
        <div class="prob-bar-track">
          <div class="prob-bar-fill id" style="width:${pctId}%"></div>
        </div>
        <span class="prob-pct">${pctId}%</span>
      </div>
      <div class="margin-note">${marginDir} &bull; ${topCutLabel}</div>
    </div>

    <div class="sim-note">
      ${ia.simulation_method === "exhaustive"
        ? `Exhaustive (${Math.pow(3, ia.other_matches_count)} scenarios)`
        : `Monte Carlo (10,000 samples)`}
      &bull; ${ia.division_table_count ?? (ia.other_matches_count + 1)} tables in division
    </div>
  `;

  return card;
}

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setLoading(show) {
  document.getElementById("loading").classList.toggle("hidden", !show);
  if (show) document.getElementById("divisions").innerHTML = "";
}

function setBanner(type, message) {
  const el = document.getElementById("status-banner");
  if (type === "hidden") {
    el.className = "banner hidden";
    el.textContent = "";
  } else {
    el.className = `banner ${type}`;
    el.textContent = message;
  }
}

function scheduleAutoRefresh() {
  clearTimeout(autoRefreshTimer);
  autoRefreshTimer = setTimeout(() => loadData(false), AUTO_REFRESH_MS);
}

// Initial load
loadData(false);

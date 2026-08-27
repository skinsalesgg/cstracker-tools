const STATS_BASE = "../data/stats";
const PROFILES_BASE = "../data/steam_profiles.json";

const tabsEl = document.getElementById("tabs");
const rowsEl = document.getElementById("rows");
const summaryEl = document.getElementById("summary");
const metaEl = document.getElementById("meta");
const categoryTitleEl = document.getElementById("categoryTitle");
const sortByEl = document.getElementById("sortBy");
const sortDirEl = document.getElementById("sortDir");
const minMessagesEl = document.getElementById("minMessages");
const searchEl = document.getElementById("search");

let indexData = null;
let categoryData = {};
let steamProfiles = {};
let activeCategoryId = null;

function fmtRate(value) {
  return `${(value * 100).toFixed(2)}%`;
}

function fmtCounter(value) {
  return Number(value).toLocaleString();
}

function steamLabel(row) {
  const profile = steamProfiles[row.steam_id];
  if (profile?.persona_name) return profile.persona_name;

  if (row.steam_url) {
    const parts = row.steam_url.split("/");
    return parts[parts.length - 1] || row.steam_id || "unknown";
  }
  return row.steam_id || "unknown";
}

function profileFor(row) {
  return steamProfiles[row.steam_id] || null;
}

function profileUrl(row) {
  const profile = profileFor(row);
  return profile?.profile_url || row.steam_url;
}

function avatarUrl(row) {
  const profile = profileFor(row);
  return profile?.avatar_medium_url || profile?.avatar_url || null;
}

function rankClass(index) {
  if (index === 0) return "gold";
  if (index === 1) return "silver";
  if (index === 2) return "bronze";
  return "";
}

function rowClass(index) {
  if (index === 0) return "top-1";
  if (index === 1) return "top-2";
  if (index === 2) return "top-3";
  return "";
}

function renderSummary(category) {
  summaryEl.innerHTML = `
    <div class="stat-card">
      <div class="label">Category</div>
      <div class="value">${category.category_label}</div>
    </div>
    <div class="stat-card">
      <div class="label">StatTrak total</div>
      <div class="value">${fmtCounter(category.total_matches)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Players flagged</div>
      <div class="value">${fmtCounter(category.players_with_matches)}<small> / ${fmtCounter(category.player_count || category.leaderboard.length)}</small></div>
    </div>
    <div class="stat-card">
      <div class="label">Messages scanned</div>
      <div class="value">${fmtCounter(category.source_message_count)}</div>
    </div>
  `;
  categoryTitleEl.textContent = category.category_label;
}

function compareRows(a, b, sortBy, sortDir) {
  const dir = sortDir === "asc" ? 1 : -1;
  if (a[sortBy] !== b[sortBy]) return (a[sortBy] - b[sortBy]) * dir;
  if (a.match_count !== b.match_count) return (a.match_count - b.match_count) * dir;
  return (a.total_messages - b.total_messages) * dir;
}

function filteredRows(category) {
  const sortBy = sortByEl.value;
  const sortDir = sortDirEl.value;
  const minMessages = Number(minMessagesEl.value || 0);
  const query = searchEl.value.trim().toLowerCase();

  return [...category.leaderboard]
    .filter((row) => row.total_messages >= minMessages)
    .filter((row) => {
      if (!query) return true;
      const profile = profileFor(row);
      const haystack = [
        row.steam_id,
        row.steam_url,
        profile?.persona_name,
        profile?.custom_url,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    })
    .sort((a, b) => compareRows(a, b, sortBy, sortDir));
}

function shouldHighlight(index, row) {
  return sortDirEl.value === "desc" && row.match_count > 0 && index < 3;
}

function renderPlayerCell(row) {
  const label = steamLabel(row);
  const avatar = avatarUrl(row);
  const url = profileUrl(row);
  const profile = profileFor(row);
  const subtitle = profile?.custom_url
    ? `@${profile.custom_url}`
    : row.steam_id || "";

  return `
    <div class="player-cell-inner">
      ${
        avatar
          ? `<img class="avatar" src="${avatar}" alt="" loading="lazy" />`
          : `<div class="avatar avatar-fallback">${label.slice(0, 1).toUpperCase()}</div>`
      }
      <div>
        <a class="player-link" href="${url}" target="_blank" rel="noreferrer">${label}</a>
        <div class="muted">${subtitle}</div>
      </div>
    </div>
  `;
}

function renderTable(category) {
  const rows = filteredRows(category);
  rowsEl.innerHTML = rows
    .map((row, index) => {
      const highlight = shouldHighlight(index, row);
      const rank = highlight ? rankClass(index) : "";
      const trClass = highlight ? rowClass(index) : row.match_count === 0 ? "zero-matches" : "";
      const steamLink = profileUrl(row);
      const counterClass = row.match_count === 0 ? "counter counter-zero" : "counter";
      return `
        <tr class="${trClass}">
          <td><span class="rank ${rank}">${index + 1}</span></td>
          <td class="player-cell">${renderPlayerCell(row)}</td>
          <td class="rate">${fmtCounter(row.total_messages)}</td>
          <td><span class="${counterClass}">${fmtCounter(row.match_count)}</span></td>
          <td class="rate"><strong>${fmtRate(row.rate_per_message)}</strong></td>
          <td>
            <div class="intel-links">
              ${row.cstracker_url ? `<a class="chip" href="${row.cstracker_url}" target="_blank" rel="noreferrer">Track</a>` : ""}
              <a class="chip" href="${steamLink}" target="_blank" rel="noreferrer">Steam</a>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderTabs() {
  tabsEl.innerHTML = indexData.categories
    .map((category) => {
      const active = category.id === activeCategoryId ? "active" : "";
      return `<button class="tab ${active}" data-category="${category.id}">${category.label}</button>`;
    })
    .join("");

  tabsEl.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", async () => {
      activeCategoryId = button.dataset.category;
      await loadCategory(activeCategoryId);
      renderTabs();
    });
  });
}

async function loadSteamProfiles() {
  try {
    const response = await fetch(PROFILES_BASE);
    if (!response.ok) return;
    const payload = await response.json();
    steamProfiles = payload.profiles || {};
  } catch (error) {
    console.warn("Steam profiles not loaded", error);
  }
}

async function loadCategory(categoryId) {
  if (!categoryData[categoryId]) {
    const response = await fetch(`${STATS_BASE}/${categoryId}.json`);
    categoryData[categoryId] = await response.json();
  }
  const category = categoryData[categoryId];
  renderSummary(category);
  renderTable(category);
}

function showError(message) {
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<div class="error shell">${message}</div>`,
  );
}

async function init() {
  try {
    await loadSteamProfiles();

    const response = await fetch(`${STATS_BASE}/index.json`);
    indexData = await response.json();
    activeCategoryId = indexData.categories[0]?.id;
    metaEl.textContent = new Date(indexData.generated_at).toLocaleString();

    renderTabs();
    await loadCategory(activeCategoryId);

    sortByEl.addEventListener("change", () => renderTable(categoryData[activeCategoryId]));
    sortDirEl.addEventListener("change", () => renderTable(categoryData[activeCategoryId]));
    minMessagesEl.addEventListener("input", () => renderTable(categoryData[activeCategoryId]));
    searchEl.addEventListener("input", () => renderTable(categoryData[activeCategoryId]));
  } catch (error) {
    showError(
      "Could not load stats. Run <code>python analyze_chat_stats.py</code> first, then serve with <code>python serve_dashboard.py</code>.",
    );
    console.error(error);
  }
}

init();

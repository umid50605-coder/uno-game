// screens/lobby.js — yangilangan (Tournament tugmasi qo'shildi)
import { api } from "../api.js";
import { setState } from "../state.js";
import { showScreen } from "../main.js";

const el = {
  list: null,
  createBtn: null,
  tournamentBtn: null,   // YANGI
  leaderboard: null,
  error: null,
  searchInput: null,
  searchBtn: null,
  randomBtn: null,
};

let refreshInterval = null;

export function initLobby() {
  el.list = document.getElementById("room-list");
  el.createBtn = document.getElementById("create-room-btn");
  el.tournamentBtn = document.getElementById("tournament-btn");   // YANGI
  el.leaderboard = document.getElementById("leaderboard");
  el.searchInput = document.getElementById("search-input");
  el.searchBtn = document.getElementById("search-btn");
  el.randomBtn = document.getElementById("random-btn");

  el.error = document.createElement("div");
  el.error.className = "lobby-error hidden";
  el.error.style.cssText = "color: #e74c3c; padding: 8px; margin: 8px; text-align: center; background: rgba(231,76,60,0.1); border-radius: 8px;";
  el.leaderboard.parentNode.insertBefore(el.error, el.leaderboard);

  el.createBtn.onclick = () => showScreen("room-choice");

  // YANGI: Tournament tugmasi bosilganda — turnir yaratish/qo'shilish ekrani.
  el.tournamentBtn.onclick = () => showScreen("tournament-lobby");

  el.searchBtn.onclick = async () => {
    const code = el.searchInput.value.trim();
    if (!code) return;
    try {
      const rooms = await api.searchRooms(code);
      if (rooms.length === 0) return showError("Xona topilmadi");
      const room = rooms[0];
      await api.joinRoom(room.id, room.is_public ? null : prompt("Xona kodini kiriting:"));
      await enterRoom(room.id);
    } catch (err) {
      showError(err.message);
    }
  };

  el.randomBtn.onclick = async () => {
    try {
      const room = await api.randomRoom();
      await api.joinRoom(room.id);
      await enterRoom(room.id);
    } catch (err) {
      showError(err.message);
    }
  };

  refreshLeaderboard();
  refreshRooms();

  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(refreshRooms, 3000);
}

export function stopLobby() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = null;
  }
}

function showError(msg) {
  if (el.error) {
    el.error.textContent = msg;
    el.error.classList.remove("hidden");
  }
}

function hideError() {
  if (el.error) el.error.classList.add("hidden");
}

async function refreshLeaderboard() {
  try {
    const data = await api.leaderboard();
    renderLeaderboard(data);
  } catch (err) {
    el.leaderboard.innerHTML = "";
  }
}

function renderLeaderboard(data) {
  const top = (data && data.top) || [];
  const me = (data && data.me) || null;

  el.leaderboard.innerHTML = "";
  if (top.length === 0 && !me) return;

  const title = document.createElement("h3");
  title.className = "leaderboard-title";
  title.textContent = "🏆 Reyting";
  el.leaderboard.appendChild(title);

  const table = document.createElement("div");
  table.className = "leaderboard-table";

  const meInTop = !!me && top.some((p) => p.telegram_id === me.telegram_id);

  top.forEach((player) => {
    const isMe = !!me && player.telegram_id === me.telegram_id;
    table.appendChild(renderLeaderboardRow(player, isMe));
  });

  if (me && !meInTop) {
    const divider = document.createElement("div");
    divider.className = "leaderboard-divider";
    divider.textContent = "⋯";
    table.appendChild(divider);
    table.appendChild(renderLeaderboardRow(me, true));
  }

  el.leaderboard.appendChild(table);
}

function forfeitStatsText(player) {
  const genuine = player.wins - player.forfeit_wins;
  const parts = [`${genuine} halol`];
  if (player.forfeit_wins > 0) parts.push(`${player.forfeit_wins} forfeit`);
  let text = `${player.wins}g (${parts.join(", ")})`;
  if (player.times_forfeited > 0) text += ` · ${player.times_forfeited}x uzilgan`;
  return text;
}

function renderLeaderboardRow(player, isMe) {
  const row = document.createElement("div");
  row.className = "leaderboard-row" + (isMe ? " me" : "");

  const rank = document.createElement("span");
  rank.className = "leaderboard-rank";
  rank.textContent = `#${player.rank}`;

  const name = document.createElement("span");
  name.className = "leaderboard-name";
  name.textContent = player.username
    ? `${player.first_name} (@${player.username})`
    : player.first_name;

  const stats = document.createElement("span");
  stats.className = "leaderboard-stats";
  stats.textContent = forfeitStatsText(player);

  const points = document.createElement("span");
  points.className = "leaderboard-points";
  points.textContent = player.rating;

  row.appendChild(rank);
  row.appendChild(name);
  row.appendChild(stats);
  row.appendChild(points);
  return row;
}

async function refreshRooms() {
  try {
    const rooms = await api.listRooms();
    el.list.innerHTML = "";
    rooms.forEach((room) => {
      const item = document.createElement("div");
      item.className = "room-item";
      const publicLabel = room.is_public ? "🌐" : "🔒";
      item.textContent = `${publicLabel} Xona #${room.id} (${room.players.length}/${room.max_players}) — ${room.status}`;
      item.onclick = async () => {
        try {
          hideError();
          let joinCode = null;
          if (!room.is_public) {
            joinCode = prompt("Xona kodini kiriting:");
            if (!joinCode) return;
          }
          await api.joinRoom(room.id, joinCode);
          await enterRoom(room.id);
        } catch (err) {
          showError(err.message);
        }
      };
      el.list.appendChild(item);
    });
  } catch (err) {
    // jim
  }
}

async function enterRoom(roomId) {
  setState({ roomId });
  showScreen("room");
}
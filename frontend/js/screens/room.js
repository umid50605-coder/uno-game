// screens/room.js — xona ichidagi kutish ekrani: ishtirokchilar, ready/wait, back
import { api } from "../api.js";
import { getState, setState } from "../state.js";
import { showScreen } from "../main.js";

const el = {
  code: null,
  list: null,
  status: null,
  readyBtn: null,
  waitBtn: null,
  backBtn: null,
};

let pollInterval = null;
let boundOnce = false;

function bindElsOnce() {
  if (boundOnce) return;
  el.code = document.getElementById("room-code");
  el.list = document.getElementById("room-players");
  el.status = document.getElementById("room-status");
  el.readyBtn = document.getElementById("room-ready-btn");
  el.waitBtn = document.getElementById("room-wait-btn");
  el.backBtn = document.getElementById("room-back-btn");
  boundOnce = true;
}

export function initRoom(roomId) {
  bindElsOnce();

  el.readyBtn.onclick = async () => {
    try {
      const room = await api.setReady(roomId);
      renderRoom(room);
     if (room.status === "playing") goToGame();
    } catch (err) {
     console.error("setReady xatosi:", err);
      el.status.textContent = "Xato: qayta urinib ko'ring.";
    }
  };

el.waitBtn.onclick = async () => {
  try {
    const room = await api.extendWait(roomId);
    renderRoom(room);
    el.status.textContent = "Kutish muddati +60 soniyaga uzaytirildi.";
  } catch (err) {
    console.error("extendWait xatosi:", err);
    el.status.textContent = "Xato: qayta urinib ko'ring.";
  }
};

  el.backBtn.onclick = async () => {
    stopRoom();
    await api.leaveRoom(roomId).catch(() => {});
    setState({ roomId: null });
    showScreen("lobby");
  };

  refreshRoom(roomId);
  stopRoom();
  pollInterval = setInterval(() => refreshRoom(roomId), 2000);
}

export function stopRoom() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

let consecutiveError = 0;

async function refreshRoom(roomId) {
  try {
    const room = await api.getRoom(roomId);
    consecutiveError = 0;
    renderRoom(room);
    if (room.status === "playing") goToGame();
    else if (room.status === "finished") _returnAfterMatch();
  } catch (err) {
    console.error("refreshRoom xatosi:", err);
    consecutiveError += 1;
    if (consecutiveError >= 3) {
      _returnAfterMatch();
    }
  }
}

function _returnAfterMatch() {
  stopRoom();
  const { tournamentId } = getState();
  if (tournamentId) {
    // Tournament match tugadi — bracket/live-view'ga qaytamiz,
    // oddiy lobbyga emas. G'olib ham, eliminated o'yinchi ham
    // shu yerdan navbatdagi round yoki final natijasini kuzatadi.
    showScreen("tournament");
  } else {
    showScreen("lobby");
  }
}

function goToGame() {
  stopRoom();
  showScreen("game");
}

function renderRoom(room) {
  const { playerId } = getState();

  el.code.textContent = `Xona #${room.code}`;

  const joinCodeEl = document.getElementById("room-join-code");
  if (room.join_code) {
    joinCodeEl.textContent = `Maxfiy kod: ${room.join_code}`;
  } else {
    joinCodeEl.textContent = "";
  }

  el.status.textContent = `${room.players.length}/${room.max_players} ishtirokchi`;
  el.list.innerHTML = "";

  room.players.forEach((p) => {
    const row = document.createElement("div");
    row.className = "room-player-row" + (p.telegram_id === playerId ? " me" : "");
    const badge = p.is_ready ? "🟢 Tayyor" : "⏳ Kutmoqda";
    row.textContent = `${p.first_name}${p.telegram_id === playerId ? " (siz)" : ""} — ${badge}`;
    el.list.appendChild(row);
  });

  const me = room.players.find((p) => p.telegram_id === playerId);
  if (me) {
    el.readyBtn.textContent = me.is_ready ? "Tayyor ✓" : "Tayyorman";
    el.readyBtn.disabled = me.is_ready;
  }
}
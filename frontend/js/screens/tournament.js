// screens/tournament.js — Tournament bracket/live-view (IN_PROGRESS holati)
import { api } from "../api.js";
import { getState, setState } from "../state.js";
import { showScreen } from "../main.js";
import { WS_BASE } from "../config.js";

const el = {
  root: null,
  status: null,
  roundsContainer: null,
  finalBanner: null,
  cancelBtn: null,
  error: null,
};

let ws = null;
let pollInterval = null;

export function initTournament() {
  el.root = document.getElementById("tournament-screen");
  el.status = document.getElementById("tournament-view-status");
  el.roundsContainer = document.getElementById("tournament-rounds");
  el.finalBanner = document.getElementById("tournament-final-banner");
  el.cancelBtn = document.getElementById("tournament-cancel-btn");
  el.error = document.getElementById("tournament-view-error");

  hideError();
  el.finalBanner.classList.add("hidden");

  const { tournamentId } = getState();
  if (!tournamentId) {
    showScreen("lobby");
    return;
  }

  el.cancelBtn.onclick = async () => {
    if (!confirm("Turnirni bekor qilishni tasdiqlaysizmi?")) return;
    try {
      await api.cancelTournament(tournamentId);
    } catch (err) {
      showError(err.message);
    }
  };

  _connectWs(tournamentId);
  _refresh();

  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(_refresh, 5000);
}

export function stopTournament() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
  if (ws) {
    try {
      ws.close();
    } catch (_) {
      // jim
    }
    ws = null;
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

function _connectWs(tournamentId) {
  const { token } = getState();
  if (!token) return;

  try {
    ws = new WebSocket(`${WS_BASE}/ws/tournament/${tournamentId}?token=${encodeURIComponent(token)}`);
  } catch (err) {
    return;
  }

  ws.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }

    if (msg.type === "tournament_state" && msg.data) {
      setState({ tournament: msg.data });
      _render(msg.data);
    } else if (msg.type === "tournament_cancelled") {
      alert("Turnir bekor qilindi.");
      setState({ tournamentId: null, tournament: null, inviteToken: null });
      showScreen("lobby");
    } else if (msg.type === "pong") {
      // heartbeat javobi
    }
  };

  ws.onclose = () => {
    ws = null;
  };

  ws.onerror = () => {
    // jim
  };
}

async function _refresh() {
  const { tournamentId } = getState();
  if (!tournamentId) return;
  try {
    const data = await api.getTournament(tournamentId);
    setState({ tournament: data });
    _render(data);
  } catch (err) {
    // jim
  }
}

function _render(data) {
  el.status.textContent = `Round ${data.current_round} — ${_statusLabel(data.status)}`;

  if (data.status === "finished") {
    _renderFinal(data);
  } else {
    el.finalBanner.classList.add("hidden");
  }

  el.roundsContainer.innerHTML = "";

  const sortedRounds = [...data.rounds].sort((a, b) => a.round_number - b.round_number);

  sortedRounds.forEach((round) => {
    const roundBlock = document.createElement("div");
    roundBlock.className = "tournament-round-block";

    const title = document.createElement("h3");
    title.textContent = `ROUND ${round.round_number}`;
    roundBlock.appendChild(title);

    round.matches.forEach((match, idx) => {
      roundBlock.appendChild(_renderMatch(match, idx + 1, data));
    });

    el.roundsContainer.appendChild(roundBlock);
  });

  _checkAndJoinMyMatch(data);
}

function _renderMatch(match, matchNumber, tournamentData) {
  const box = document.createElement("div");
  box.className = "tournament-match-box";

  const statusIcon = match.status === "finished" ? "🟢" : match.status === "playing" ? "🟡" : "🔴";
  const header = document.createElement("div");
  header.className = "tournament-match-header";
  header.textContent = `${statusIcon} Match ${matchNumber}`;
  box.appendChild(header);

  const playersInMatch = _findPlayersForMatch(tournamentData, match);
  const playersLine = document.createElement("div");
  playersLine.className = "tournament-match-players";
  playersLine.textContent = playersInMatch.length > 0
    ? playersInMatch.join(" vs ")
    : "";
  box.appendChild(playersLine);

  const statusLine = document.createElement("div");
  statusLine.className = "tournament-match-status";
  if (match.status === "finished" && match.winner_telegram_id) {
    statusLine.textContent = `Winner: ${match.winner_telegram_id}`;
  } else {
    statusLine.textContent = _matchStatusLabel(match.status);
  }
  box.appendChild(statusLine);

  return box;
}

function _findPlayersForMatch(tournamentData, match) {
  return match.player_telegram_ids || [];
}

function _checkAndJoinMyMatch(data) {
  const { playerId, roomId } = getState();

  const me = data.players.find((p) => p.telegram_id === playerId);
  if (!me || me.status !== "active") return;

  const currentRound = data.rounds.find((r) => r.round_number === data.current_round);
  if (!currentRound) return;

  const myMatch = currentRound.matches.find(
    (m) => m.status !== "finished" && (m.player_telegram_ids || []).includes(playerId)
  );
  if (!myMatch) return;

  if (roomId === myMatch.room_id) return;

  setState({ roomId: myMatch.room_id });
  showScreen("room");
}

function _renderFinal(data) {
  el.finalBanner.classList.remove("hidden");
  el.finalBanner.innerHTML = `
    <h2>🏆 Tournament Champion</h2>
    <p>${data.winner_telegram_id}</p>
    <p>Reward: +${data.reward_points} ball</p>
  `;

  const backBtn = document.createElement("button");
  backBtn.textContent = "Lobbyga qaytish";
  backBtn.onclick = () => {
    setState({ tournamentId: null, tournament: null, inviteToken: null });
    showScreen("lobby");
  };
  el.finalBanner.appendChild(backBtn);
}

function _statusLabel(status) {
  const map = {
    registration: "Ro'yxatdan o'tish",
    in_progress: "Davom etmoqda",
    finished: "Yakunlangan",
    cancelled: "Bekor qilingan",
  };
  return map[status] || status;
}

function _matchStatusLabel(status) {
  const map = {
    waiting: "Kutilmoqda",
    playing: "O'ynalmoqda",
    finished: "Tugadi",
  };
  return map[status] || status;
}
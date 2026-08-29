// screens/tournamentLobby.js — Tournament yaratish / ro'yxatdan o'tish / ready
import { api } from "../api.js";
import { getState, setState } from "../state.js";
import { showScreen } from "../main.js";
import { tg } from "../config.js";

const el = {
  root: null,
  createBtn: null,
  joinInput: null,
  joinBtn: null,
  status: null,
  playerList: null,
  countdown: null,
  readyBtn: null,
  leaveBtn: null,
  copyLinkBtn: null,
  inviteLinkBox: null,
  error: null,
};

let pollInterval = null;
let countdownInterval = null;

export function initTournamentLobby() {
  el.root = document.getElementById("tournament-lobby-screen");
  el.createBtn = document.getElementById("tournament-create-btn");
  el.joinInput = document.getElementById("tournament-join-input");
  el.joinBtn = document.getElementById("tournament-join-btn");
  el.status = document.getElementById("tournament-status");
  el.playerList = document.getElementById("tournament-player-list");
  el.countdown = document.getElementById("tournament-countdown");
  el.readyBtn = document.getElementById("tournament-ready-btn");
  el.leaveBtn = document.getElementById("tournament-leave-btn");
  el.copyLinkBtn = document.getElementById("tournament-copy-link-btn");
  el.inviteLinkBox = document.getElementById("tournament-invite-link");
  el.error = document.getElementById("tournament-lobby-error");

  hideError();

  const { tournamentId, inviteToken } = getState();

  if (tournamentId) {
    showLobbyView();
    if (!inviteToken) {
      _tryAutoJoinOrRefresh();
    } else {
      _startPolling();
    }
    return;
  }

  showEntryView();
  document.getElementById("tournament-back-btn").onclick = () => showScreen("lobby");

  el.createBtn.onclick = async () => {
    try {
      hideError();
      const result = await api.createTournament();
      setState({
        tournamentId: result.id,
        tournament: result,
        inviteToken: result.invite_token,
      });
      showLobbyView();
      _startPolling();
    } catch (err) {
      showError(err.message);
    }
  };

  el.joinBtn.onclick = async () => {
    const raw = el.joinInput.value.trim();
    if (!raw) return;
    try {
      hideError();
      const { tournamentId: tid, inviteToken: token } = _parseInviteInput(raw);
      const result = await api.joinTournament(tid, token);
      setState({ tournamentId: tid, tournament: result, inviteToken: null });
      showLobbyView();
      _startPolling();
    } catch (err) {
      showError(err.message);
    }
  };
}

export function stopTournamentLobby() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
  if (countdownInterval) {
    clearInterval(countdownInterval);
    countdownInterval = null;
  }
}

function _parseInviteInput(raw) {
  // Foydalanuvchi yoki to'liq havolani (t.me/...?startapp=trny_ID_TOKEN)
  // yoki to'g'ridan-to'g'ri "ID_TOKEN" formatini kiritishi mumkin.
  const match = raw.match(/trny_(\d+)_([\w-]+)/);
  if (match) {
    return { tournamentId: Number(match[1]), inviteToken: match[2] };
  }
  const parts = raw.split("_");
  if (parts.length === 2) {
    return { tournamentId: Number(parts[0]), inviteToken: parts[1] };
  }
  throw new Error("Taklif havolasi formati noto'g'ri");
}

function showEntryView() {
  document.getElementById("tournament-entry-view").classList.remove("hidden");
  document.getElementById("tournament-lobby-view").classList.add("hidden");
}

function showLobbyView() {
  document.getElementById("tournament-entry-view").classList.add("hidden");
  document.getElementById("tournament-lobby-view").classList.remove("hidden");
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

async function _tryAutoJoinOrRefresh() {
  const { tournamentId, inviteToken } = getState();
  try {
    const data = await api.getTournament(tournamentId);
    const { playerId } = getState();
    const alreadyIn = data.players.some((p) => p.telegram_id === playerId);
    if (!alreadyIn && inviteToken) {
      const joined = await api.joinTournament(tournamentId, inviteToken);
      setState({ tournament: joined });
    } else {
      setState({ tournament: data });
    }
    _startPolling();
  } catch (err) {
    showError(err.message);
  }
}

function _startPolling() {
  _refresh();
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(_refresh, 2000);
}

async function _refresh() {
  const { tournamentId } = getState();
  if (!tournamentId) return;
  try {
    const data = await api.getTournament(tournamentId);
    setState({ tournament: data });
    _render(data);

    if (data.status === "in_progress") {
      showScreen("tournament");
    } else if (data.status === "cancelled") {
      alert("Turnir bekor qilindi.");
      setState({ tournamentId: null, tournament: null, inviteToken: null });
      showScreen("lobby");
    }
  } catch (err) {
    // jim — vaqtinchalik tarmoq xatosi bo'lishi mumkin
  }
}

function _render(data) {
  el.status.textContent = `Holat: ${_statusLabel(data.status)}`;

  el.playerList.innerHTML = "";
  data.players.forEach((p) => {
    const row = document.createElement("div");
    row.className = "tournament-player-row";
    row.textContent = `${p.ready ? "✓" : "○"} ${p.telegram_id}`;
    el.playerList.appendChild(row);
  });

  const { inviteToken, tournamentId, playerId } = getState();
    if (inviteToken) {
    el.inviteLinkBox.classList.remove("hidden");
    el.copyLinkBtn.onclick = async () => {
      const link = await _buildInviteLink(tournamentId, inviteToken);
      await navigator.clipboard?.writeText(link);
      alert("Havola nusxalandi!");
    };
  } else {
    el.inviteLinkBox.classList.add("hidden");
  }

  const me = data.players.find((p) => p.telegram_id === playerId);
  if (me) {
    el.readyBtn.textContent = me.ready ? "✓ Tayyor" : "Tayyor";
    el.readyBtn.classList.toggle("active", me.ready);
    el.readyBtn.onclick = async () => {
      try {
        const updated = await api.setTournamentReady(tournamentId, !me.ready);
        setState({ tournament: updated });
        _render(updated);
      } catch (err) {
        showError(err.message);
      }
    };
  }

  el.leaveBtn.onclick = async () => {
    try {
      await api.leaveTournament(tournamentId);
      setState({ tournamentId: null, tournament: null, inviteToken: null });
      showScreen("lobby");
    } catch (err) {
      showError(err.message);
    }
  };

  if (data.registration_expires_at) {
    _startCountdown(data.registration_expires_at);
  }
}

function _startCountdown(expiresAtIso) {
  if (countdownInterval) clearInterval(countdownInterval);
  const expiresAt = new Date(expiresAtIso).getTime();

  const tick = () => {
    const remaining = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
    el.countdown.textContent = `Ro'yxatdan o'tish: ${remaining}s`;
    if (remaining <= 0 && countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }
  };
  tick();
  countdownInterval = setInterval(tick, 1000);
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

let _cachedBotUsername = null;

async function _getBotUsername() {
  if (_cachedBotUsername) return _cachedBotUsername;
  try {
    const { bot_username } = await api.getConfig();
    _cachedBotUsername = bot_username;
    return _cachedBotUsername;
  } catch (err) {
    console.error("Bot username olishda xato:", err);
    return null;
  }
}

async function _buildInviteLink(tournamentId, inviteToken) {
  const payload = `trny_${tournamentId}_${inviteToken}`;
  const botUsername = await _getBotUsername();
  if (!botUsername) {
    // Zaxira variant — kamida ichki formatni beradi, umuman ishlamay qolmasin
    return payload;
  }
  return `https://t.me/${botUsername}?startapp=${payload}`;
}
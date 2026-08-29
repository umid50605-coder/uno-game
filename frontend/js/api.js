// api.js — barcha REST chaqiruvlar shu yerdan o'tadi (auth header avtomatik qo'shiladi)
import { API_BASE } from "./config.js";
import { getState } from "./state.js";

async function request(path, options = {}) {
  const { token } = getState();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let body = {};
    try {
      body = await res.json();
    } catch (_) {
      // JSON bo'lmasa, body {} bo'lib qoladi
    }
    const detail = body.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
      ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
      : `${path} so'rovi muvaffaqiyatsiz (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  auth: (initData) => request("/auth", { method: "POST", body: JSON.stringify({ initData }) }),
  me: () => request("/me"),
  leaderboard: () => request("/leaderboard"),
  listRooms: () => request("/rooms"),
  createRoom: (isPublic, joinCode = null) => request("/rooms", {
    method: "POST",
    body: JSON.stringify({ is_public: isPublic, join_code: joinCode }),
  }),
  joinRoom: (roomId, joinCode = null) => request(`/rooms/${roomId}/join`, {
    method: "POST",
    body: JSON.stringify({ join_code: joinCode }),
  }),
  getRoom: (roomId) => request(`/rooms/${roomId}`),
  leaveRoom: (roomId) => request(`/rooms/${roomId}/leave`, { method: "POST" }),
  setReady: (roomId) => request(`/rooms/${roomId}/ready`, { method: "POST" }),
  extendWait: (roomId) => request(`/rooms/${roomId}/wait`, { method: "POST" }),
  searchRooms: (code) => request(`/rooms/search?code=${encodeURIComponent(code)}`),
  randomRoom: () => request("/rooms/random"),

  // ---------------- Tournament ----------------
  // create/get/join/leave/ready/cancel — hammasi backend/api/routes/tournament.py bilan mos.
  createTournament: () => request("/tournaments", { method: "POST" }),
  getTournament: (tournamentId) => request(`/tournaments/${tournamentId}`),
  joinTournament: (tournamentId, inviteToken) => request(`/tournaments/${tournamentId}/join`, {
    method: "POST",
    body: JSON.stringify({ invite_token: inviteToken }),
  }),
  leaveTournament: (tournamentId) => request(`/tournaments/${tournamentId}/leave`, { method: "POST" }),
  setTournamentReady: (tournamentId, ready = true) => request(`/tournaments/${tournamentId}/ready`, {
    method: "POST",
    body: JSON.stringify({ ready }),
  }),
  cancelTournament: (tournamentId) => request(`/tournaments/${tournamentId}/cancel`, { method: "POST" }),
    getBracket: (tournamentId) => request(`/tournaments/${tournamentId}/bracket`),

  // ---------------- Config ----------------
  getConfig: () => request("/config"),
};
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
    // 403 xatolarni alohida otamiz, chunki frontend ularni UI'da ko'rsatishi kerak
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
  
  // Xonalar ro'yxati (faqat public, ochiq xonalar)
  listRooms: () => request("/rooms"),
  
  // Xona yaratish (isPublic: true -> public, false -> security; joinCode faqat security uchun kerak)
  createRoom: (isPublic, joinCode = null) => request("/rooms", {
    method: "POST",
    body: JSON.stringify({ is_public: isPublic, join_code: joinCode }),
  }),
  
  // Xonaga qo'shilish (security xonalarda joinCode kiritiladi)
  joinRoom: (roomId, joinCode = null) => request(`/rooms/${roomId}/join`, {
    method: "POST",
    body: JSON.stringify({ join_code: joinCode }),
  }),
  
  // Xona haqida ma'lumot (telegram_id avtomatik token orqali aniqlanadi)
  getRoom: (roomId) => request(`/rooms/${roomId}`),
  
  // Xonani tark etish
  leaveRoom: (roomId) => request(`/rooms/${roomId}/leave`, { method: "POST" }),
  
  // Tayyorlik holatini o'zgartirish
  setReady: (roomId) => request(`/rooms/${roomId}/ready`, { method: "POST" }),
  
  // Kutish vaqtini uzaytirish
  extendWait: (roomId) => request(`/rooms/${roomId}/wait`, { method: "POST" }),
  
  // Kod orqali xona qidirish (security ham, public ham topiladi)
  searchRooms: (code) => request(`/rooms/search?code=${encodeURIComponent(code)}`),
  
  // Tasodifiy public xona topish
  randomRoom: () => request("/rooms/random"),
};
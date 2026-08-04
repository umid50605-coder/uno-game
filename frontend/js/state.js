// state.js — butun app uchun yagona holat manbai (single source of truth)
const state = {
  token: null,
  playerId: null,
  roomId: null,
  screen: "lobby", // "lobby" | "game"
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
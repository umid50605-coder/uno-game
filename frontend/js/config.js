// config.js — manzillar va Telegram WebApp sozlamalari
export const API_BASE = window.location.origin;
export const WS_BASE = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export const tg = window.Telegram?.WebApp;

export function initTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();
}
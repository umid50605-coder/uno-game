// ws-client.js — WebSocket ulanishini boshqaradi, xabarlarni "type" bo'yicha tarqatadi.
// Stage 14: kutilmagan uzilishda avtomatik qayta ulanish (backoff bilan).
//
// TUZATILDI (MEDIUM — uzoq muddatli JWT WS URL'da oshkor bo'lishi): avval
// connect(roomId, token) orqali asosiy session token (24 soat amal qiladi)
// to'g'ridan-to'g'ri WS URL query-string'iga qo'yilardi. Endi connect(roomId)
// faqat roomId oladi — har bir ulanish/qayta-ulanish OLDIDAN api.getWsTicket()
// orqali (Authorization header bilan, URL'da EMAS) 30 soniyalik qisqa
// muddatli ticket so'raladi, va shu ticket WS URL'ga qo'yiladi.
import { WS_BASE } from "./config.js";
import { api } from "./api.js";

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000];
const MAX_RECONNECT_ATTEMPTS = 8;

class WSClient {
  constructor() {
    this.socket = null;
    this.handlers = {};
    this.roomId = null;
    this.intentionalClose = false;
    this.reconnectAttempt = 0;
    this.reconnectTimer = null;

    this.heartbeatTimer = null;
    this.pongTimeoutTimer = null;

    this.HEARTBEAT_INTERVAL_MS = 5000;
    this.PONG_TIMEOUT_MS = 3000;
  }

  connect(roomId) {
    this.roomId = roomId;
    this.intentionalClose = false;
    this.reconnectAttempt = 0;

    this._stopHeartbeat();

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this._openSocket();
  }

  async _openSocket() {
    let ticket;
    try {
      const result = await api.getWsTicket();
      ticket = result.ticket;
    } catch (err) {
      // Ticket olib bo'lmadi (masalan tarmoq xatosi yoki session tugagan) —
      // oddiy uzilish sifatida ko'rib, qayta ulanish jadvaliga qo'shamiz.
      (this.handlers["_disconnected"] || []).forEach((fn) => fn());
      this._scheduleReconnect();
      return;
    }

    // connect()/qayta ulanish orasida intentionalClose bo'lishi mumkin
    // (masalan foydalanuvchi ekrandan chiqib ketgan bo'lsa) — ticket
    // so'rovi tugaguncha holat o'zgargan bo'lishi mumkin, shuning uchun
    // qayta tekshiramiz.
    if (this.intentionalClose) return;

    const url = `${WS_BASE}/ws/rooms/${this.roomId}?token=${encodeURIComponent(ticket)}`;
    this.socket = new WebSocket(url);

    this.socket.onopen = () => {
      if (this.reconnectAttempt > 0) {
        (this.handlers["_reconnected"] || []).forEach((fn) => fn());
      }
      this.reconnectAttempt = 0;
      this._startHeartbeat();
    };

    this.socket.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "pong") {
        this._handlePong();
        return;
      }

      (this.handlers[data.type] || []).forEach((fn) => fn(data));
    };

    this.socket.onclose = () => {
      this._stopHeartbeat();
      (this.handlers["_close"] || []).forEach((fn) => fn());

      if (!this.intentionalClose) {
        (this.handlers["_disconnected"] || []).forEach((fn) => fn());
        this._scheduleReconnect();
      }
    };
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      (this.handlers["_reconnect_failed"] || []).forEach((fn) => fn());
      return;
    }
    const delay = RECONNECT_DELAYS_MS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.intentionalClose) this._openSocket();
    }, delay);
  }

  _startHeartbeat() {
    this._stopHeartbeat();

    this.heartbeatTimer = setInterval(() => {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        return;
      }
      this.send("ping");
      this._startPongTimeout();
    }, this.HEARTBEAT_INTERVAL_MS);
  }

  _startPongTimeout() {
    this._stopPongTimeout();

    this.pongTimeoutTimer = setTimeout(() => {
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.close(4000, "Heartbeat timeout");
      }
    }, this.PONG_TIMEOUT_MS);
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this._stopPongTimeout();
  }

  _stopPongTimeout() {
    if (this.pongTimeoutTimer) {
      clearTimeout(this.pongTimeoutTimer);
      this.pongTimeoutTimer = null;
    }
  }

  _handlePong() {
    this._stopPongTimeout();
  }

  on(type, fn) {
    (this.handlers[type] ||= []).push(fn);
  }

  send(action, payload = {}) {
    if (!this.socket) return;
    if (this.socket.readyState !== WebSocket.OPEN) return;

    this.socket.send(JSON.stringify({ action, ...payload }));
  }

  close() {
    this.intentionalClose = true;
    this._stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
  }
}

export const wsClient = new WSClient();
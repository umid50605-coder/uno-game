// ws-client.js — WebSocket ulanishini boshqaradi, xabarlarni "type" bo'yicha tarqatadi.
// Stage 14: kutilmagan uzilishda avtomatik qayta ulanish (backoff bilan).
import { WS_BASE } from "./config.js";

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000];
const MAX_RECONNECT_ATTEMPTS = 8;

class WSClient {
  constructor() {
    this.socket = null;
    this.handlers = {};
    this.roomId = null;
    this.token = null;
    this.intentionalClose = false;
    this.reconnectAttempt = 0;
    this.reconnectTimer = null;

    this.heartbeatTimer = null;
    this.pongTimeoutTimer = null;

    this.HEARTBEAT_INTERVAL_MS = 5000;
    this.PONG_TIMEOUT_MS = 3000;
  }

  connect(roomId, token) {
    this.roomId = roomId;
    this.token = token;
    this.intentionalClose = false;
    this.reconnectAttempt = 0;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this._openSocket();
  }

  _openSocket() {
    const url = `${WS_BASE}/ws/rooms/${this.roomId}?token=${this.token}`;

    console.log(url);

    this.socket = new WebSocket(url);

    this.socket.onopen = () => {

      console.log("SOCKET OPEN");

      if (this.reconnectAttempt > 0) {
          (this.handlers["_reconnected"] || []).forEach(fn => fn());
      }

      this.reconnectAttempt = 0;

      this._startHeartbeat();
    };

    this.socket.onmessage = (event) => {

      console.log("RECV:", event.data);

      const data = JSON.parse(event.data);

      if (data.type === "pong"){
        this._handlePong();
        return;
      }

      (this.handlers[data.type] || []).forEach(fn => fn(data));
    };

    this.socket.onclose = (event) => {

      console.log(
          "CLOSE",
          "code =", event.code,
          "reason =", event.reason,
          "wasClean =", event.wasClean
      );

      this._stopHeartbeat();

      (this.handlers["_close"] || []).forEach(fn => fn());

      if (!this.intentionalClose) {
        (this.handlers["_disconnected"] || []).forEach(fn => fn());
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

    console.log("Heartbeat started");

    this.heartbeatTimer = setInterval(() => {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        return;
      }

      console.log("PING");
      
      this.send("ping");

      this._startPongTimeout();

    }, this.HEARTBEAT_INTERVAL_MS);
  }

  _startPongTimeout() {
    this._startPongTimeout();

    this.pongTimeoutTimer = setTimeout(() => {

      console.log("PONG TIMEOUT");

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
    console.log("PONG");

    this._stopPongTimeout();
  }

  on(type, fn) {
    (this.handlers[type] ||= []).push(fn);
  }

  send(action, payload = {}) {

    console.log("SEND:", action, payload);

    if (!this.socket) {
        console.log("Socket yo'q");
        return;
    }

    console.log("readyState =", this.socket.readyState);

    if (this.socket.readyState !== WebSocket.OPEN) {
        console.log("Socket OPEN emas");
        return;
    }

    this.socket.send(JSON.stringify({
        action,
        ...payload
    }));
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
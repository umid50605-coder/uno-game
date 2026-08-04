// screens/game.js — o'yin ekrani. Stage 12 (kartalar/UNO/stacking) + Stage 14
// (uzilish/qayta ulanish/forfeit holati).
import { wsClient } from "../ws-client.js";
import { getState, setState } from "../state.js";
import { showScreen } from "../main.js";

const RING_HEX = { red: "#e24b4a", yellow: "#f1c40f", green: "#2ecc71", blue: "#3498db" };
const WILD_RING = "#f2f2f2";

const GAME_OVER_REDIRECT_DELAY_MS = 2500;
const FORFEITED_REDIRECT_DELAY_MS = 2000;

let selectedWildCardIndex = null;
let pendingUnoCall = false;
let lastState = null;
let gameOverTimer = null;
let disconnectCountdownTimer = null;

export function initGame() {
  const { roomId, token } = getState();
  wsClient.connect(roomId, token);

  wsClient.on("game_state", renderState);
  wsClient.on("game_over", (data) => {
    stopDisconnectCountdown();
    showGameOver(data.winner);
  });
  wsClient.on("error", (data) => showError(data.message));
  wsClient.on("uno_called", (data) => showToast(unoCalledText(data.player_id)));
  wsClient.on("uno_caught", (data) => showToast(unoCaughtText(data)));

  wsClient.on("_disconnected", () => showConnectionBanner("Ulanish uzildi, qayta ulanmoqda..."));
  wsClient.on("_reconnected", () => hideConnectionBanner());
  wsClient.on("_reconnect_failed", () => showError("Ulanish tiklanmadi. Sahifani qayta yuklang."));
  wsClient.on("player_disconnected", (data) => {
    showToast(`${getPlayerName(data.player_id)} uzildi...`);
    startDisconnectCountdown(data);
  });
  wsClient.on("player_reconnected", (data) => {
    showToast(`${getPlayerName(data.player_id)} qaytdi`);
    stopDisconnectCountdown();
  });
    wsClient.on("player_forfeited", (data) => {
    showToast(`${getPlayerName(data.player_id)} o'yindan chiqarildi`);
    stopDisconnectCountdown();
  });

  document.getElementById("draw-btn").onclick = () => wsClient.send("draw_card");
  document.getElementById("uno-btn").onclick = onUnoBtnClick;
  document.querySelectorAll("#color-picker button").forEach((btn) => {
    btn.onclick = () => chooseColor(btn.dataset.color);
  });
}

export function stopGame() {
  stopDisconnectCountdown();
  if (gameOverTimer) {
    clearTimeout(gameOverTimer);
    gameOverTimer = null;
  }
  wsClient.close();
  lastState = null;
  pendingUnoCall = false;
  selectedWildCardIndex = null;
  document.getElementById("game-over").classList.add("hidden");
  hideConnectionBanner();
}

function renderState(state) {
  lastState = state;
  const { playerId } = getState();

  document.getElementById("top-card").innerHTML = renderCard(state.top_card, state.current_color);
  document.getElementById("draw-pile-count").textContent = state.draw_pile_count;

  renderTurnIndicator(state, playerId);
  renderStackIndicator(state);
  renderUnoButton(state);

  const opponentsEl = document.getElementById("opponents");
  opponentsEl.innerHTML = "";
  state.opponents.forEach((opp) => {
    const div = document.createElement("div");
    div.className =
      "opponent" +
      (opp.catchable ? " catchable" : "") +
      (opp.connected === false ? " disconnected" : "");

    const label = document.createElement("span");
    label.textContent = `${opp.name}: ${opp.card_count} karta`;
    div.appendChild(label);

    if (opp.connected === false) {
      const badge = document.createElement("span");
      badge.className = "disconnected-badge";
      badge.textContent = "uzildi";
      div.appendChild(badge);
    }

    if (opp.uno_called && opp.card_count === 1) {
      const badge = document.createElement("span");
      badge.className = "uno-badge";
      badge.textContent = "UNO!";
      div.appendChild(badge);
    }

    if (opp.catchable) {
      const catchBtn = document.createElement("button");
      catchBtn.className = "catch-btn";
      catchBtn.textContent = `Tut! (+${2})`;
      catchBtn.onclick = () => wsClient.send("catch_uno", { target_id: opp.player_id });
      div.appendChild(catchBtn);
    }

    opponentsEl.appendChild(div);
  });

  const handEl = document.getElementById("my-hand");
  handEl.innerHTML = "";
  state.your_hand.forEach((card, idx) => {
    const cardEl = document.createElement("div");
    cardEl.className = "card";
    cardEl.innerHTML = renderCard(card, state.current_color);
    cardEl.onclick = () => onCardClick(idx, card);
    handEl.appendChild(cardEl);
  });
}

function renderTurnIndicator(state, playerId) {
  const el = document.getElementById("turn-indicator");
  if (state.current_player === playerId) {
    el.textContent =
      state.pending_draw > 0
        ? `Sizning navbatingiz! Javob bering yoki torting (+${state.pending_draw})`
        : "Sizning navbatingiz!";
  } else {
    el.textContent = `Navbat: ${getPlayerName(state.current_player)}`;
  }
}

function renderStackIndicator(state) {
  const el = document.getElementById("stack-indicator");
  if (state.pending_draw > 0) {
    const label = state.pending_draw_type === "wild4" ? "WILD+4" : "DRAW2";
    el.textContent = `Yig'ilgan: +${state.pending_draw} (${label} zanjiri)`;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

function renderUnoButton(state) {
  const btn = document.getElementById("uno-btn");
  const handSize = state.your_hand.length;

  if (handSize === 1 || handSize === 2) {
    btn.classList.remove("hidden");
  } else {
    btn.classList.add("hidden");
    pendingUnoCall = false;
  }

  if (handSize === 1 && state.your_uno_called) {
    btn.classList.add("armed");
    btn.textContent = "UNO! ✓";
  } else if (pendingUnoCall) {
    btn.classList.add("armed");
    btn.textContent = "UNO! (tayyor)";
  } else {
    btn.classList.remove("armed");
    btn.textContent = "UNO!";
  }
}

function cardFileName(card) {
  if (card.color === null) {
    return card.value === "wild4" ? "wild_draw4.png" : "wild.png";
  }
  return `${card.color}_${card.value}.png`;
}

function renderCard(card, fallbackColor) {
  const color = card.color || fallbackColor;
  const ring = color ? (RING_HEX[color] || WILD_RING) : WILD_RING;

  let icon = "";
  if (card.value === "skip") {
    icon = `<circle cx="45" cy="64" r="15" fill="none" stroke="#fff" stroke-width="4"/>
            <line x1="35" y1="64" x2="55" y2="64" stroke="#fff" stroke-width="4" stroke-linecap="round"/>`;
  } else if (card.value === "reverse") {
    icon = `<path d="M 27,55 A 18,18 0 0 1 60,50" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round"/>
            <polygon points="60,50 53,47 55,56" fill="#fff"/>
            <path d="M 63,73 A 18,18 0 0 1 30,78" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round"/>
            <polygon points="30,78 37,81 35,72" fill="#fff"/>`;
  } else if (card.value === "wild" || card.value === "wild4") {
    icon = `<path d="M 33,52 L 39,68 L 24,58 L 45,58 L 30,68 Z" fill="#fff"/>`;
  }

  const label = card.value === "draw2" ? "+2" : card.value === "wild4" ? "" : "";
  const corner = { skip: "S", reverse: "R", draw2: "+2", wild: "W", wild4: "+4" }[card.value] || card.value;

  return `
    <svg viewBox="0 0 90 135" class="card-svg">
      <rect x="2" y="2" width="86" height="131" rx="10" fill="#0d0d0f" stroke="${ring}" stroke-width="2"/>
      <rect x="6" y="6" width="78" height="123" rx="7" fill="none" stroke="${ring}" stroke-width="1"/>
      <ellipse cx="45" cy="64" rx="25" ry="38" fill="none" stroke="${ring}" stroke-width="2.5"/>
      ${icon || `<text x="45" y="84" text-anchor="middle" class="card-main">${label || corner}</text>`}
      <text x="14" y="22" class="card-corner">${corner}</text>
      <text x="76" y="117" text-anchor="end" class="card-corner">${corner}</text>
    </svg>`;
}

function onCardClick(index, card) {
  if (card.color === null) {
    selectedWildCardIndex = index;
    document.getElementById("color-picker").classList.remove("hidden");
    return;
  }
  wsClient.send("play_card", { card_index: index, chosen_color: null, call_uno: pendingUnoCall });
  pendingUnoCall = false;
}

function chooseColor(color) {
  document.getElementById("color-picker").classList.add("hidden");
  if (selectedWildCardIndex !== null) {
    wsClient.send("play_card", { card_index: selectedWildCardIndex, chosen_color: color, call_uno: pendingUnoCall });
    selectedWildCardIndex = null;
    pendingUnoCall = false;
  }
}

function onUnoBtnClick() {
  if (!lastState) return;

  if (lastState.your_hand.length === 1) {
    wsClient.send("call_uno");
  } else {
    pendingUnoCall = !pendingUnoCall;
    renderUnoButton(lastState);
  }
}

function getPlayerName(playerId) {
  if (lastState && Array.isArray(lastState.opponents)) {
    const opp = lastState.opponents.find((o) => o.player_id === playerId);
    if (opp) return opp.name;
  }
  return `O'yinchi #${playerId}`;
}

function unoCalledText(playerId) {
  const { playerId: myId } = getState();
  return playerId === myId ? "Siz 'UNO!' dedingiz" : `${getPlayerName(playerId)}: UNO!`;
}

function unoCaughtText(data) {
  const { playerId: myId } = getState();
  if (data.target_id === myId) {
    return `Tutildingiz! +${data.penalty} karta tortdingiz`;
  }
  if (data.catcher_id === myId) {
    return `${getPlayerName(data.target_id)}ni tutdingiz! +${data.penalty} karta berdi`;
  }
  return `${getPlayerName(data.catcher_id)}, ${getPlayerName(data.target_id)}ni tutdi (+${data.penalty})`;
}

function showGameOver(winnerId) {
  const { playerId } = getState();
  const el = document.getElementById("game-over");
  el.classList.remove("hidden");
  el.textContent = winnerId === playerId ? "Siz yutdingiz! 🎉" : `${getPlayerName(winnerId)} yutdi.`;

  if (gameOverTimer) clearTimeout(gameOverTimer);
  gameOverTimer = setTimeout(() => {
    gameOverTimer = null;
    setState({ roomId: null });
    showScreen("lobby");
  }, GAME_OVER_REDIRECT_DELAY_MS);
}

function showError(message) {
  const el = document.getElementById("game-error");
  el.textContent = message;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 2500);
}

function showToast(message) {
  const el = document.getElementById("game-toast");
  el.textContent = message;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 2000);
}

function showConnectionBanner(message) {
  const el = document.getElementById("connection-banner");
  el.textContent = message;
  el.classList.remove("hidden");
}

function hideConnectionBanner() {
  document.getElementById("connection-banner").classList.add("hidden");
}

function startDisconnectCountdown(data) {
  stopDisconnectCountdown();
  const deadline = new Date(data.disconnected_at).getTime() + data.grace_period_seconds * 1000;
  const bannerEl = document.getElementById("opponent-disconnect-banner");
  bannerEl.classList.remove("hidden");

  const tick = () => {
    const remaining = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    bannerEl.textContent = `${getPlayerName(data.player_id)} uzildi — ${remaining}s ichida qaytmasa, siz g'olib bo'lasiz`;
    if (remaining <= 0) stopDisconnectCountdown();
  };
  tick();
  disconnectCountdownTimer = setInterval(tick, 1000);
}

function stopDisconnectCountdown() {
  if (disconnectCountdownTimer) {
    clearInterval(disconnectCountdownTimer);
    disconnectCountdownTimer = null;
  }
  document.getElementById("opponent-disconnect-banner").classList.add("hidden");
}
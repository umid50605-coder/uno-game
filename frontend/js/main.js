// main.js — kirish nuqtasi: Telegram auth, ekranlarni almashtirish
import { initTelegram, tg } from "./config.js";
import { api } from "./api.js";
import { getState, setState } from "./state.js";
import { initLobby, stopLobby } from "./screens/lobby.js";
import { initRoom, stopRoom } from "./screens/room.js";
import { initGame, stopGame } from "./screens/game.js";
import { initRoomChoice, stopRoomChoice } from "./screens/roomChoice.js";
import { initCreateCode, stopCreateCode } from "./screens/createCode.js";

export function showScreen(name) {
  // Barcha ekranlarni yashirish
  const screens = ["lobby-screen", "room-screen", "game-screen", "room-choice-screen", "create-code-screen"];
  screens.forEach(id => {
    document.getElementById(id).classList.add("hidden");
  });

  // Faol ekranni ko‘rsatish
  document.getElementById(name + "-screen").classList.remove("hidden");

  // To‘xtatish
  if (name !== "lobby") stopLobby();
  if (name !== "room") stopRoom();
  if (name !== "game") stopGame();
  if (name !== "room-choice") stopRoomChoice();
  if (name !== "create-code") stopCreateCode();

  // Boshlash
  if (name === "lobby") initLobby();
  else if (name === "room") initRoom(getState().roomId);
  else if (name === "game") initGame();
  else if (name === "room-choice") initRoomChoice();
  else if (name === "create-code") initCreateCode();
}

async function bootstrap() {
  initTelegram();
  const initData = tg?.initData || "";
  if (!initData) {
    document.body.innerHTML = `<p style="color:#f55;padding:20px">DIAGNOSTIKA: tg.initData bo'sh keldi.</p>`;
    return;
  }
  try {
    const authResult = await api.auth(initData);
    const { token, user } = authResult;
    setState({ token, playerId: user.id });
    showScreen("lobby");
  } catch (err) {
    document.body.innerHTML = `<p style="color:#f55;padding:20px">Xatolik: ${err.message}</p>`;
  }
}

bootstrap().catch((err) => {
  document.body.innerHTML = `<p style="color:#f55;padding:20px">Xatolik: ${err.message}</p>`;
});
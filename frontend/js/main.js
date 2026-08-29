// main.js — kirish nuqtasi: Telegram auth, ekranlarni almashtirish
import { initTelegram, tg } from "./config.js";
import { api } from "./api.js";
import { getState, setState } from "./state.js";
import { initLobby, stopLobby } from "./screens/lobby.js";
import { initRoom, stopRoom } from "./screens/room.js";
import { initGame, stopGame } from "./screens/game.js";
import { initRoomChoice, stopRoomChoice } from "./screens/roomChoice.js";
import { initCreateCode, stopCreateCode } from "./screens/createCode.js";
import { initTournamentLobby, stopTournamentLobby } from "./screens/tournamentLobby.js";
import { initTournament, stopTournament } from "./screens/tournament.js";

const SCREENS = [
  "lobby",
  "room",
  "game",
  "room-choice",
  "create-code",
  "tournament-lobby",
  "tournament",
];

export function showScreen(name) {
  SCREENS.forEach((id) => {
    document.getElementById(id + "-screen").classList.add("hidden");
  });

  document.getElementById(name + "-screen").classList.remove("hidden");

  if (name !== "lobby") stopLobby();
  if (name !== "room") stopRoom();
  if (name !== "game") stopGame();
  if (name !== "room-choice") stopRoomChoice();
  if (name !== "create-code") stopCreateCode();
  if (name !== "tournament-lobby") stopTournamentLobby();
  if (name !== "tournament") stopTournament();

  if (name === "lobby") initLobby();
  else if (name === "room") initRoom(getState().roomId);
  else if (name === "game") initGame();
  else if (name === "room-choice") initRoomChoice();
  else if (name === "create-code") initCreateCode();
  else if (name === "tournament-lobby") initTournamentLobby();
  else if (name === "tournament") initTournament();
}

function _parseStartParam() {
  // Tournament deep link endi query-string orqali keladi:
  // <WEBAPP_URL>?tournament=<id>&invite_token=<token>
  // (bot/keyboards.py'dagi tournament_keyboard() shu formatda URL quradi).
  try {
    const params = new URLSearchParams(window.location.search);
    const tournamentIdRaw = params.get("tournament");
    const inviteToken = params.get("invite_token");
    if (!tournamentIdRaw || !inviteToken) return null;
    const tournamentId = Number(tournamentIdRaw);
    if (!Number.isFinite(tournamentId)) return null;
    return { tournamentId, inviteToken };
  } catch (_) {
    return null;
  }
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

    const deepLink = _parseStartParam();
    if (deepLink) {
      setState({ tournamentId: deepLink.tournamentId, inviteToken: deepLink.inviteToken });
      showScreen("tournament-lobby");
      return;
    }

    showScreen("lobby");
  } catch (err) {
    document.body.innerHTML = `<p style="color:#f55;padding:20px">Xatolik: ${err.message}</p>`;
  }
}

bootstrap().catch((err) => {
  document.body.innerHTML = `<p style="color:#f55;padding:20px">Xatolik: ${err.message}</p>`;
});
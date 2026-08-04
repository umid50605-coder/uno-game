import { showScreen } from "../main.js";

export function initRoomChoice() {
  document.getElementById("choice-public-btn").onclick = async () => {
    try {
      const { api } = await import("../api.js");
      const room = await api.createRoom(true);
      const { setState } = await import("../state.js");
      setState({ roomId: room.id });
      showScreen("room");
    } catch (err) {
      alert("Xatolik: " + err.message);
    }
  };

  document.getElementById("choice-security-btn").onclick = () => {
    showScreen("create-code");   // ✅ "-screen" qo'shmasdan, faqat asosiy nom
  };

  document.querySelector("#room-choice-screen .back-btn").onclick = () => showScreen("lobby");
}

export function stopRoomChoice() {}
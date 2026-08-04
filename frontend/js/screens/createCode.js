import { showScreen } from "../main.js";

export function initCreateCode() {
  const codeInput = document.getElementById("code-input");
  const createBtn = document.getElementById("code-create-btn");

  createBtn.onclick = async () => {
    const code = codeInput.value.trim();
    if (!code) return alert("Kodni kiriting");
    try {
      const { api } = await import("../api.js");
      const room = await api.createRoom(false, code);
      const { setState } = await import("../state.js");
      setState({ roomId: room.id });
      showScreen("room");
    } catch (err) {
      alert("Xatolik: " + err.message);
    }
  };

  document.querySelector("#create-code-screen .back-btn").onclick = () => showScreen("room-choice");
}

export function stopCreateCode() {}
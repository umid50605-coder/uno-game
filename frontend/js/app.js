(function () {
    "use strict";

    const statusEl = document.getElementById("status-text");

    if (!window.Telegram || !window.Telegram.WebApp) {
        if (statusEl) {
            statusEl.textContent = "Bu ilova faqat Telegram ichida ishlaydi.";
        }
        console.error("Telegram WebApp SDK topilmadi.");
        return;
    }

    const tg = window.Telegram.WebApp;

    tg.ready();
    tg.expand();

    let sessionToken = null;

    async function authenticate() {
        try {
            const response = await fetch("/auth", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    initData: tg.initData
                })
            });

            if (!response.ok) {
                throw new Error(`Server xatosi: ${response.status}`);
            }

            const data = await response.json();

            if (!data.ok) {
                statusEl.textContent = "Autentifikatsiya muvaffaqiyatsiz.";
                return;
            }

            sessionToken = data.token;
            statusEl.textContent = "Telegram Mini App ishlayapti.";
            initGame(data.user);
        } catch (error) {
            console.error("Autentifikatsiyada xatolik:", error);
            statusEl.textContent = "Serverga ulanishda xatolik yuz berdi.";
        }
    }

    async function fetchMe() {
        if (!sessionToken) {
            return;
        }

        try {
            const response = await fetch("/me", {
                headers: {
                    Authorization: `Bearer ${sessionToken}`
                }
            });

            if (!response.ok) {
                throw new Error(`Server xatosi: ${response.status}`);
            }

            const data = await response.json();
            console.log("Joriy foydalanuvchi (/me):", data);
        } catch (error) {
            console.error("/me so'rovida xatolik:", error);
        }
    }

    function initGame(user) {
        // O'yin logikasi shu yerdan boshlanadi
        console.log("Foydalanuvchi autentifikatsiya qilindi:", user);
        fetchMe();
    }

    authenticate();
})();
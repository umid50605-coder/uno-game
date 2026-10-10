# UNO Game

Telegram Mini App UNO Game

Backend: Python (FastAPI)

Bot: Aiogram

Frontend: HTML, CSS, JavaScript


## Deployment cheklovlari (MUHIM)

**Backend faqat BITTA worker / BITTA instance sifatida ishga tushirilishi shart.**

Quyidagilar process-local (faqat bitta Python process xotirasida yashaydi):

- `GameManager` — faol `GameEngine` obyektlari (o'yin holati)
- `ConnectionManager` — ochiq WebSocket ulanishlari
- tournament `threading.RLock` lock'lari
- har bir xona uchun "game finish" lock'lari

Bir nechta worker yoki instance ishga tushirilsa, bir xonaning o'yin holati faqat
bitta workerda bo'ladi, boshqa worker uni bilmaydi: broadcast'lar yetib bormaydi,
o'yinchilar bir-birining yurishini ko'rmaydi.

- `backend/Dockerfile` `uvicorn ... --workers 1` bilan ishga tushiradi
  (`WEB_CONCURRENCY` qiymatidan qat'i nazar).
- Render'da servisni 1 instance'dan ortiq **scale qilmang**.
- Ko'p-instance qo'llab-quvvatlash uchun tashqi holat (Redis/DB) va taqsimlangan
  lock kerak bo'ladi — hozircha qo'shilmagan.

DB tomonda ba'zi himoyalar (room qatori `FOR UPDATE`, turnir qatori `FOR UPDATE`,
`room.status == FINISHED` idempotentlik tekshiruvi) ko'p-instance holatida ham
reyting/reward ikki marta qo'llanmasligiga yordam beradi, lekin bu o'yin
holatining process-local ekanligini o'zgartirmaydi.


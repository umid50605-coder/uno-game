"""backend/services/tournament/locks.py

Har bir tournament uchun alohida concurrency-qulf.

MUHIM (2026-09-08 TUZATILDI — avval DEADLOCK bor edi):
Bu yerda threading.RLock ishlatiladi, oddiy threading.Lock EMAS, chunki
chaqiruv zanjiri xuddi shu thread ichida o'z-o'ziga qayta kirishi mumkin:

    handle_tournament_match_finished()   # lock oladi
      -> _maybe_advance_after_match()    # (hali lock band, matches.py)
        -> advance_round()               # (hali lock band, lifecycle.py)
          -> create_round()              # XUDDI SHU tournament_id uchun
                                          # lockni qayta so'raydi!

Oddiy threading.Lock bir xil thread tomonidan qayta-qayta olinishini
QO'LLAB-QUVVATLAMAYDI — shuning uchun yuqoridagi zanjir chaqirilganda
(ya'ni bitta round ichida 2 yoki undan ko'p match bo'lib, ular orqali
keyingi bosqichga o'tish kerak bo'lganda) butun so'rov ABADIY osilib
qolardi (deadlock). Bu ayni shu fayl bir nechta modulga bo'lib
chiqarilishidan OLDIN ham xuddi shunday mavjud edi va bo'lish jarayonida
o'zgarishsiz ko'chib o'tgan edi.

threading.RLock xuddi shu threadga qayta kirishga ruxsat beradi (ichki
hisoblagich orqali — necha marta acquire() qilingan bo'lsa, shuncha
marta release() qilinishi kerak), boshqa threadlarni esa hamon to'g'ri
bloklaydi. Bu — bir nechta funksiya/fayl bo'ylab tarqalgan "kim hozir
lockni ushlab turibdi" degan qo'lda kuzatuvga qaraganda ancha ishonchli
yechim, ayniqsa kod keyinchalik yana refaktor qilinishi mumkinligini
hisobga olsak.

Bu izohni keyingi refaktoringlarda olib tashlamang — aynan shu narsa
xatoning qaytalanishini oldini oladi.
"""
import threading

_tournament_locks: dict[int, threading.RLock] = {}
_tournament_locks_meta_lock = threading.Lock()


def _get_tournament_lock(tournament_id: int) -> threading.RLock:
    with _tournament_locks_meta_lock:
        lock = _tournament_locks.get(tournament_id)
        if lock is None:
            lock = threading.RLock()
            _tournament_locks[tournament_id] = lock
        return lock
"""
Action Dispatcher.

Vazifasi FAQAT: WebSocket orqali kelgan xom action payload'ni
tekshirib (validatsiya), tegishli GameEngine metodiga yo'naltirish.

Bu qatlam ATAYLAB quyidagilarni qilmaydi:
  - authentication (buni ws_auth.py bajaradi)
  - WebSocket connect/broadcast/send (buni connection_manager.py bajaradi)
  - DB bilan ishlash (bu yerda Session yo'q)
  - rating berish (rating_service.py)
  - finish_game/cancel_game chaqirish (routes/websocket/finish.py)

GameEngine metodlari qaytargan {"ok": bool, ...} natija o'zgarishsiz
qaytariladi — natijaga qarab broadcast/finish qarorini chaqiruvchi
tomon (odatda api/routes/websocket/actions.py) qabul qiladi.

DIQQAT — TAKRORLANISH XAVFI:
routes/websocket/actions.py allaqachon "message_loop -> GameEngine"
oralig'ida turibdi va aynan shu ishni (action -> metod, validatsiya)
o'zi bajarayotgan bo'lishi juda ehtimol. Bu faylni ishlatishdan oldin
o'sha faylni solishtiring:
  - agar actions.py'da xuddi shunday if/elif validatsiya zanjiri
    bo'lsa -> bu fayl ORTIQCHA, o'chirib tashlang;
  - agar actions.py hozircha validatsiyasiz to'g'ridan-to'g'ri
    GameEngine metodini chaqirsa -> actions.py'ni shu yerdagi
    dispatch_action() ni chaqiradigan qilib almashtiring (validatsiya
    faqat BITTA joyda qolishi uchun).
"""

from typing import Any

from services.game_engine import GameEngine

VALID_COLORS = {"red", "yellow", "green", "blue"}


class ActionValidationError(Exception):
    """Payload strukturasi/turi noto'g'ri bo'lganda ko'tariladi.
    O'yin qoidasi buzilishi BUNDAN EMAS — buni GameEngine o'zi
    {"ok": False, "error": ...} bilan qaytaradi (masalan: navbat
    emasligi, noto'g'ri karta)."""


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ActionValidationError(f"'{key}' butun son bo'lishi kerak")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise ActionValidationError(f"'{key}' matn (string) bo'lishi kerak")
    return value


def _optional_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ActionValidationError(f"'{key}' bool (true/false) bo'lishi kerak")
    return value


def dispatch_action(game: GameEngine, player_id: int, payload: dict[str, Any]) -> dict:
    """
    game — shu xonaning GameEngine instansi (chaqiruvchi tomon
        game_manager.get(room_id) orqali oladi).
    player_id — telegram_id. Auth ws_auth.py tomonidan allaqachon
        tasdiqlangan deb hisoblanadi, bu yerda qayta tekshirilmaydi.
    payload — JSON'dan allaqachon dict'ga parse qilingan xabar,
        masalan {"action": "play_card", "card_index": 2, ...}.

    Qaytaradi: GameEngine metodi qaytargan natija, yoki payload
    strukturasi noto'g'ri bo'lsa {"ok": False, "error": "..."}.
    """
    action = payload.get("action")

    try:
        if action == "play_card":
            card_index = _require_int(payload, "card_index")
            chosen_color = _optional_str(payload, "chosen_color")
            if chosen_color is not None and chosen_color not in VALID_COLORS:
                raise ActionValidationError("Noto'g'ri rang")
            call_uno = _optional_bool(payload, "call_uno", default=False)
            return game.play_card(
                player_id=player_id,
                card_index=card_index,
                chosen_color=chosen_color,
                call_uno=call_uno,
            )

        if action == "draw_card":
            return game.draw_card(player_id=player_id)

        if action == "call_uno":
            return game.call_uno(player_id=player_id)

        if action == "catch_uno":
            target_id = _require_int(payload, "target_id")
            return game.catch_uno(catcher_id=player_id, target_id=target_id)

        return {"ok": False, "error": f"Noma'lum action: {action!r}"}

    except ActionValidationError as e:
        return {"ok": False, "error": str(e)}
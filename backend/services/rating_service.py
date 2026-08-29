"""
backend/services/rating_service.py
Stage 12.1 — Reyting xizmati.
"""

import logging

from sqlalchemy.orm import Session

from models.user import User

logger = logging.getLogger(__name__)

RATING_WIN = 10
RATING_LOSS = 5


def apply_game_result(db: Session, player_ids: list[int], winner_id: int, via_forfeit: bool = False) -> None:
    """player_ids va winner_id — telegram_id (GameEngine bilan bir xil id turi).
    via_forfeit=True bo'lsa, bu g'alaba raqib uzilib forfeit bo'lgani uchun qozonilgan
    (halol o'yin orqali emas) — shunda winner.forfeit_wins ham +1 bo'ladi."""
    users = db.query(User).filter(User.telegram_id.in_(player_ids)).all()
    for user in users:
        user.games_played += 1
        if user.telegram_id == winner_id:
            user.wins += 1
            user.rating += RATING_WIN
            if via_forfeit:
                user.forfeit_wins += 1
        else:
            user.rating = max(0, user.rating - RATING_LOSS)

    db.commit()

    logger.info(
        "Reyting yangilandi: g'olib=%s (forfeit=%s), ishtirokchilar=%s",
        winner_id, via_forfeit, player_ids,
    )


def apply_forfeit_result(db: Session, forfeiter_id: int, remaining_ids: list[int]) -> None:
    """O'yin hali davom etayotganda (remaining_ids kamida 2 kishi) bitta
    o'yinchi forfeit bo'lganda chaqiriladi."""
    forfeiter = db.query(User).filter(User.telegram_id == forfeiter_id).first()
    if forfeiter is not None:
        forfeiter.games_played += 1
        forfeiter.rating = max(0, forfeiter.rating - RATING_LOSS)

    if remaining_ids:
        share = RATING_WIN // len(remaining_ids)
        remaining_users = db.query(User).filter(User.telegram_id.in_(remaining_ids)).all()
        for user in remaining_users:
            user.rating += share

    db.commit()

    logger.info(
        "Forfeit ball: chiqqan=%s (games_played+1, rating-%d), qolganlar=%s (+%d/kishi)",
        forfeiter_id,
        RATING_LOSS,
        remaining_ids,
        RATING_WIN // len(remaining_ids) if remaining_ids else 0,
    )


def apply_tournament_reward(db: Session, winner_telegram_id: int, reward_points: int) -> None:
    """Tournament g'olibiga bir martalik reward beradi.

    MUHIM DIZAYN QARORI: bu funksiya games_played/wins'ni OSHIRMAYDI —
    faqat rating'ga qo'shadi. Sabab: tournament ichida g'olib allaqachon
    har bir match uchun apply_game_result() orqali o'z games_played/wins
    balllarini olib bo'lgan (har bir match — oddiy UNO o'yini). Agar bu
    yerda yana games_played+1 qilsak, "1 ta tournament g'alabasi" leaderboard
    tarixida yolg'on ravishda "N+1 ta o'yin" bo'lib ko'rinadi.

    Chaqiruvchi tomon (tournament_service.finish_tournament) DOUBLE REWARD
    bo'lmasligini ta'minlashi kerak — ya'ni bu funksiya faqat tournament
    status FINISHED'ga o'tayotgan aynan bir martalik tranzaksiyada
    chaqirilishi shart."""
    user = db.query(User).filter(User.telegram_id == winner_telegram_id).first()
    if user is None:
        logger.warning(
            "apply_tournament_reward: foydalanuvchi topilmadi telegram_id=%s",
            winner_telegram_id,
        )
        return

    user.rating += reward_points
    db.commit()

    logger.info(
        "Tournament reward berildi: winner=%s +%d ball",
        winner_telegram_id, reward_points,
    )
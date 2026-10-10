"""Tournament testlari (audit F-01, F-06..F-09, F-14, F-15)."""
import asyncio
import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.routes.tournament import _cancel_tournament_in_thread
from api.routes.websocket import finish as finish_mod
from api.routes.websocket.finish import finish_game
from api.routes.websocket.state import game_manager
from core.database import SessionLocal
from models.room import Room, RoomPlayer, RoomStatus
from models.tournament import (
    Tournament,
    TournamentMatch,
    TournamentPlayer,
    TournamentPlayerStatus,
    TournamentRound,
    TournamentRoundStatus,
    TournamentStatus,
)
from models.user import User
from services import room_service, tournament_service
from services.tournament import lifecycle

from .conftest import make_users, stats

BASE = 100
WIN = 10
REWARD = lifecycle.REWARD_PER_PARTICIPANT


# ---------------------------------------------------------- yordamchilar

def make_tournament(n: int, base: int = 2000):
    users = make_users(n, base)
    with SessionLocal() as db:
        t = Tournament(
            creator_telegram_id=users[0],
            invite_token_hash="x",
            status=TournamentStatus.REGISTRATION,
            participant_count=n,
        )
        db.add(t)
        db.flush()
        for tid in users:
            db.add(TournamentPlayer(tournament_id=t.id, telegram_id=tid, ready=True))
        db.commit()
        tid_ = t.id
    return tid_, users


def start(tournament_id: int):
    with SessionLocal() as db:
        return tournament_service.start_tournament(db, tournament_id)


def t_state(tournament_id: int) -> dict:
    with SessionLocal() as db:
        t = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        rounds = db.query(TournamentRound).filter(TournamentRound.tournament_id == tournament_id).order_by(TournamentRound.round_number).all()
        return {
            "status": t.status,
            "current_round": t.current_round,
            "winner": t.winner_telegram_id,
            "reward": t.reward_points,
            "rounds": [(r.round_number, r.status) for r in rounds],
            "players": {p.telegram_id: p.status for p in t.players},
        }


def open_matches(tournament_id: int) -> list[tuple[int, list[int]]]:
    """Hali tugamagan matchlar: [(room_id, [telegram_ids])]."""
    with SessionLocal() as db:
        ms = (
            db.query(TournamentMatch)
            .join(TournamentRound, TournamentRound.id == TournamentMatch.round_id)
            .filter(TournamentRound.tournament_id == tournament_id, TournamentMatch.status != RoomStatus.FINISHED)
            .order_by(TournamentMatch.id)
            .all()
        )
        out = []
        for m in ms:
            rows = (
                db.query(User.telegram_id)
                .join(RoomPlayer, RoomPlayer.user_id == User.id)
                .filter(RoomPlayer.room_id == m.room_id)
                .order_by(User.telegram_id)
                .all()
            )
            out.append((m.room_id, [r[0] for r in rows]))
        return out


async def finish_match(room_id: int, players: list[int], winner: int) -> bool:
    game = game_manager.get_or_create(room_id, list(players), {p: f"P{p}" for p in players})
    game.winner = winner
    return await finish_game(room_id=room_id, game=game, winner=winner)


def count(model) -> int:
    with SessionLocal() as db:
        return db.query(model).count()


# ---------------------------------------------------------- Tournament 13-17

async def test_13_single_match_finishes_tournament_and_pays_reward():
    tid, users = make_tournament(2)
    start(tid)
    [(room_id, players)] = open_matches(tid)
    assert sorted(players) == users

    assert await finish_match(room_id, players, users[0]) is True

    s = t_state(tid)
    assert s["status"] == TournamentStatus.FINISHED and s["winner"] == users[0]
    assert s["reward"] == 2 * REWARD
    assert s["rounds"] == [(1, TournamentRoundStatus.FINISHED)]
    assert stats(users[0])["rating"] == BASE + WIN + 2 * REWARD
    assert stats(users[1])["rating"] == BASE - 5


async def test_14_15_16_17_full_bracket_round_creation_final_and_reward():
    tid, users = make_tournament(8)
    start(tid)
    ms = open_matches(tid)
    assert len(ms) == 2 and t_state(tid)["current_round"] == 1

    # (14) bitta match tugadi -> round hali tugamagan, keyingi round yo'q
    (room1, p1), (room2, p2) = ms
    w1, w2 = p1[0], p2[0]
    await finish_match(room1, p1, w1)
    s = t_state(tid)
    assert s["rounds"] == [(1, TournamentRoundStatus.IN_PROGRESS)]
    assert s["status"] == TournamentStatus.IN_PROGRESS

    # (14,15) ikkinchi match ham tugadi -> round FINISHED + 2-round yaratildi
    await finish_match(room2, p2, w2)
    s = t_state(tid)
    assert s["rounds"] == [(1, TournamentRoundStatus.FINISHED), (2, TournamentRoundStatus.IN_PROGRESS)]
    assert s["current_round"] == 2 and s["status"] == TournamentStatus.IN_PROGRESS
    for u in users:
        expected = TournamentPlayerStatus.ACTIVE if u in (w1, w2) else TournamentPlayerStatus.ELIMINATED
        assert s["players"][u] == expected

    # (16) final
    [(room3, p3)] = open_matches(tid)
    assert sorted(p3) == sorted([w1, w2])
    await finish_match(room3, p3, w1)

    s = t_state(tid)
    assert s["status"] == TournamentStatus.FINISHED and s["winner"] == w1
    assert s["rounds"][-1] == (2, TournamentRoundStatus.FINISHED)

    # (17) reward: 8 ishtirokchi * REWARD, faqat bir marta, faqat g'olibga
    assert s["reward"] == 8 * REWARD
    assert stats(w1)["rating"] == BASE + WIN + WIN + 8 * REWARD
    assert stats(w2)["rating"] == BASE + WIN - 5


async def test_18_24_duplicate_finish_and_reward_applied_once():
    tid, users = make_tournament(2)
    start(tid)
    [(room_id, players)] = open_matches(tid)
    await finish_match(room_id, players, users[0])
    rating_after = stats(users[0])["rating"]

    # takroriy tournament finish -> rad etiladi
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            tournament_service.finish_tournament(db, tid, users[0])
        assert ei.value.status_code == 400
    # takroriy T2 chaqiruvlari va recovery sweep -> hech narsa o'zgarmaydi
    for _ in range(3):
        with SessionLocal() as db:
            tournament_service.handle_tournament_match_finished(db, room_id, users[0])
        with SessionLocal() as db:
            assert tournament_service.recover_stalled_rounds(db) == 0
    # takroriy o'yin finish (RAM bayrog'i yo'q) ham
    await finish_match(room_id, players, users[0])

    assert stats(users[0])["rating"] == rating_after
    assert t_state(tid)["reward"] == 2 * REWARD


async def test_24_concurrent_t2_transitions_pay_reward_once():
    tid, users = make_tournament(2)
    start(tid)
    [(room_id, players)] = open_matches(tid)

    # T1'ni qo'lda bajaramiz, T2'ni ko'p threaddan bir vaqtda ishga tushiramiz.
    real_t2 = finish_mod._tournament_transition_sync
    monkey_calls = []

    def skip_t2(room, winner):
        monkey_calls.append((room, winner))

    finish_mod._tournament_transition_sync = skip_t2
    try:
        await finish_match(room_id, players, users[0])
    finally:
        finish_mod._tournament_transition_sync = real_t2
    assert t_state(tid)["status"] == TournamentStatus.IN_PROGRESS   # T2 hali bajarilmagan

    results = await asyncio.gather(*[
        asyncio.to_thread(real_t2, room_id, users[0]) for _ in range(6)
    ] + [
        asyncio.to_thread(_sweep) for _ in range(3)
    ], return_exceptions=True)
    assert not [r for r in results if isinstance(r, Exception)], results

    assert t_state(tid)["status"] == TournamentStatus.FINISHED
    assert stats(users[0])["rating"] == BASE + WIN + 2 * REWARD


def _sweep():
    with SessionLocal() as db:
        return tournament_service.recover_stalled_rounds(db)


# ---------------------------------------------------------- 19: callback failure

async def test_19_tournament_callback_failure_is_not_silent_and_is_recoverable(monkeypatch, caplog):
    tid, users = make_tournament(8)
    start(tid)
    (room1, p1), (room2, p2) = open_matches(tid)
    w1, w2 = p1[0], p2[0]
    await finish_match(room1, p1, w1)

    def boom(room_id, winner):
        raise RuntimeError("turnir logikasi yiqildi")

    monkeypatch.setattr(finish_mod, "_tournament_transition_sync", boom)
    caplog.set_level("ERROR")
    ok = await finish_match(room2, p2, w2)
    monkeypatch.undo()

    # O'yin natijasi saqlangan (rollback QILINMAGAN) ...
    assert ok is True
    assert stats(w2)["rating"] == BASE + WIN
    with SessionLocal() as db:
        assert db.query(Room).filter(Room.id == room2).first().status == RoomStatus.FINISHED
        m = db.query(TournamentMatch).filter(TournamentMatch.room_id == room2).first()
        assert m.status == RoomStatus.FINISHED and m.winner_telegram_id == w2
    # ... xato JIM yutilmagan (ERROR log) ...
    assert any("TOURNAMENT TRANSITION MUVAFFAQIYATSIZ" in r.getMessage() for r in caplog.records)
    # ... turnir "yarim" holatda emas: round 1 hali IN_PROGRESS, keyingi round yo'q
    s = t_state(tid)
    assert s["rounds"] == [(1, TournamentRoundStatus.IN_PROGRESS)]

    # Recovery sweep qayta urinadi va o'tishni BIR marta bajaradi
    assert _sweep() == 1
    s = t_state(tid)
    assert s["rounds"] == [(1, TournamentRoundStatus.FINISHED), (2, TournamentRoundStatus.IN_PROGRESS)]
    assert _sweep() == 0
    assert count(TournamentRound) == 2
    assert len(open_matches(tid)) == 1


# ---------------------------------------------------------- 20: transaction rollback

def test_20a_start_tournament_is_atomic(monkeypatch):
    tid, users = make_tournament(8)
    real = room_service.create_tournament_match_room
    calls = {"n": 0}

    def flaky(db, group):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("ikkinchi xona yaratilmadi")
        return real(db, group)

    monkeypatch.setattr(room_service, "create_tournament_match_room", flaky)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            tournament_service.start_tournament(db, tid)
    monkeypatch.undo()

    # Hech narsa yarim commit bo'lmadi
    s = t_state(tid)
    assert s["status"] == TournamentStatus.REGISTRATION and s["current_round"] == 0
    assert s["rounds"] == []
    assert count(TournamentMatch) == 0 and count(Room) == 0
    assert len(s["players"]) == 8

    # Qayta urinish muvaffaqiyatli
    start(tid)
    assert len(open_matches(tid)) == 2 and t_state(tid)["current_round"] == 1


async def test_20b_finish_with_reward_failure_rolls_back_whole_transition(monkeypatch):
    tid, users = make_tournament(2)
    start(tid)
    [(room_id, players)] = open_matches(tid)

    def boom(db, telegram_id, points):
        raise RuntimeError("reward yiqildi")

    monkeypatch.setattr(lifecycle, "apply_tournament_reward", boom)
    await finish_match(room_id, players, users[0])
    monkeypatch.undo()

    # "FINISHED, lekin reward berilmagan" holati YO'Q: butun T2 rollback
    s = t_state(tid)
    assert s["status"] == TournamentStatus.IN_PROGRESS and s["winner"] is None and s["reward"] == 0
    assert s["rounds"] == [(1, TournamentRoundStatus.IN_PROGRESS)]
    assert stats(users[0])["rating"] == BASE + WIN          # faqat o'yin g'alabasi, reward yo'q

    # Recovery: turnir yakunlanadi va reward aynan bir marta
    assert _sweep() == 1
    s = t_state(tid)
    assert s["status"] == TournamentStatus.FINISHED and s["winner"] == users[0]
    assert stats(users[0])["rating"] == BASE + WIN + 2 * REWARD
    assert _sweep() == 0
    assert stats(users[0])["rating"] == BASE + WIN + 2 * REWARD


async def test_20c_next_round_creation_failure_rolls_back_round_finish(monkeypatch):
    tid, users = make_tournament(8)
    start(tid)
    (room1, p1), (room2, p2) = open_matches(tid)

    def boom(db, group):
        raise RuntimeError("keyingi round xonasi yaratilmadi")

    await finish_match(room1, p1, p1[0])
    monkeypatch.setattr(room_service, "create_tournament_match_room", boom)
    await finish_match(room2, p2, p2[0])
    monkeypatch.undo()

    s = t_state(tid)
    # round FINISHED + current_round++ + eliminatsiya — hech biri commit bo'lmagan
    assert s["rounds"] == [(1, TournamentRoundStatus.IN_PROGRESS)]
    assert s["current_round"] == 1
    assert all(st == TournamentPlayerStatus.ACTIVE for st in s["players"].values())
    assert count(Room) == 2

    assert _sweep() == 1
    s = t_state(tid)
    assert s["current_round"] == 2 and len(s["rounds"]) == 2
    assert len(open_matches(tid)) == 1


# ---------------------------------------------------------- F-01: T2 alohida thread + sessiya

async def test_t2_runs_in_worker_thread_with_own_session(monkeypatch):
    tid, users = make_tournament(2)
    start(tid)
    [(room_id, players)] = open_matches(tid)
    seen = {}
    real = tournament_service.handle_tournament_match_finished

    def spy(db, rid, winner):
        seen["thread"] = threading.get_ident()
        seen["db"] = db
        return real(db, rid, winner)

    monkeypatch.setattr(tournament_service, "handle_tournament_match_finished", spy)
    await finish_match(room_id, players, users[0])

    assert seen["thread"] != threading.get_ident(), "T2 worker threadda ishlashi kerak"
    assert seen["db"] is not None
    assert t_state(tid)["status"] == TournamentStatus.FINISHED


# ---------------------------------------------------------- F-15 validation

@pytest.mark.parametrize("status", [TournamentStatus.REGISTRATION, TournamentStatus.CANCELLED, TournamentStatus.FINISHED])
def test_15_finish_tournament_rejects_invalid_statuses(status):
    tid, users = make_tournament(2)
    with SessionLocal() as db:
        t = db.query(Tournament).filter(Tournament.id == tid).first()
        t.status = status
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            tournament_service.finish_tournament(db, tid, users[0])
        assert ei.value.status_code == 400
    with SessionLocal() as db:
        assert db.query(User).filter(User.telegram_id == users[0]).first().rating == BASE


def test_15b_finish_tournament_rejects_non_participant():
    tid, users = make_tournament(2)
    start(tid)
    outsider = make_users(1, base=9000)[0]
    with SessionLocal() as db:
        with pytest.raises(HTTPException):
            tournament_service.finish_tournament(db, tid, outsider)
    assert t_state(tid)["status"] == TournamentStatus.IN_PROGRESS
    assert stats(outsider)["rating"] == BASE


# ---------------------------------------------------------- cancel (atomic + own session)

def test_cancel_is_atomic_and_uses_own_session():
    tid, users = make_tournament(8)
    start(tid)
    res = _cancel_tournament_in_thread(tid, users[0])
    assert res["status"] == "cancelled"
    s = t_state(tid)
    assert s["status"] == TournamentStatus.CANCELLED
    assert open_matches(tid) == []
    assert all(st == TournamentRoundStatus.FINISHED for _, st in s["rounds"])


def test_cancel_failure_leaves_tournament_untouched(monkeypatch):
    tid, users = make_tournament(8)
    start(tid)

    def boom(db, tournament_id):
        raise RuntimeError("matchlarni yopib bo'lmadi")

    monkeypatch.setattr(lifecycle, "_cancel_active_matches_for_tournament", boom)
    with pytest.raises(RuntimeError):
        _cancel_tournament_in_thread(tid, users[0])
    monkeypatch.undo()

    assert t_state(tid)["status"] == TournamentStatus.IN_PROGRESS
    assert len(open_matches(tid)) == 2


async def test_game_finishing_after_cancel_does_not_resurrect_tournament():
    tid, users = make_tournament(2)
    start(tid)
    [(room_id, players)] = open_matches(tid)
    _cancel_tournament_in_thread(tid, users[0])

    await finish_match(room_id, players, users[0])
    s = t_state(tid)
    assert s["status"] == TournamentStatus.CANCELLED and s["reward"] == 0
    assert stats(users[0])["rating"] == BASE + WIN        # o'yin natijasi baribir yoziladi


# ---------------------------------------------------------- F-14 UNIQUE(room_id)

def test_14_room_id_unique_constraint_in_fresh_schema():
    tid, users = make_tournament(2)
    start(tid)
    [(room_id, _)] = open_matches(tid)
    with SessionLocal() as db:
        rnd = db.query(TournamentRound).first()
        db.add(TournamentMatch(round_id=rnd.id, room_id=room_id, status=RoomStatus.PLAYING))
        with pytest.raises(IntegrityError):
            db.commit()


def test_14b_schema_hardening_applies_to_existing_database():
    """create_all() mavjud jadvalga constraint qo'shmaydi — main.py'dagi idempotent
    buyruq production bazada uni yaratishi kerak."""
    import main

    with SessionLocal() as db:
        db.execute(text("ALTER TABLE tournament_matches DROP CONSTRAINT IF EXISTS uq_tournament_match_room_id"))
        db.execute(text("DROP INDEX IF EXISTS uq_tournament_match_room_id"))
        db.commit()

    main._ensure_schema_hardening()
    main._ensure_schema_hardening()           # idempotent: ikkinchi chaqiruv xato bermaydi

    with SessionLocal() as db:
        names = [r[0] for r in db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='tournament_matches'"))]
    assert "uq_tournament_match_room_id" in names


def test_14c_schema_hardening_does_not_crash_startup_when_duplicates_exist(caplog):
    import main

    tid, users = make_tournament(2)
    start(tid)
    [(room_id, _)] = open_matches(tid)
    with SessionLocal() as db:
        db.execute(text("ALTER TABLE tournament_matches DROP CONSTRAINT IF EXISTS uq_tournament_match_room_id"))
        db.execute(text("DROP INDEX IF EXISTS uq_tournament_match_room_id"))
        rnd = db.query(TournamentRound).first()
        db.add(TournamentMatch(round_id=rnd.id, room_id=room_id, status=RoomStatus.PLAYING))
        db.commit()

    caplog.set_level("ERROR")
    main._ensure_schema_hardening()            # istisno ko'tarmasligi kerak
    assert any("UNIQUE" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------- qo'shimcha: start + DB-darajasidagi idempotentlik

def test_start_removes_not_ready_players_and_excludes_them_from_matches():
    """start_tournament endi round'ni commit'dan OLDIN yaratadi — ready bo'lmagan
    (o'chirilgan) o'yinchi `tournament.players` kolleksiyasida qolib, matchga
    tushib qolmasligi kerak."""
    tid, users = make_tournament(5)
    ghost = users[-1]
    with SessionLocal() as db:
        p = db.query(TournamentPlayer).filter(TournamentPlayer.telegram_id == ghost).first()
        p.ready = False
        db.commit()

    start(tid)

    s = t_state(tid)
    assert ghost not in s["players"], "ready bo'lmagan o'yinchi o'chirilgan"
    assert s["status"] == TournamentStatus.IN_PROGRESS
    in_matches = [pid for _, players in open_matches(tid) for pid in players]
    assert ghost not in in_matches
    assert sorted(in_matches) == sorted(users[:-1])
    with SessionLocal() as db:
        assert db.query(Tournament).filter(Tournament.id == tid).first().participant_count == 4


async def test_24b_db_row_lock_alone_prevents_double_transition(monkeypatch):
    """Process-local RLock O'CHIRILGAN holatda ham (ko'p-worker ehtimoli) tournament
    qatoridagi FOR UPDATE + status tekshiruvi reward'ni ikki marta bermaydi."""
    from contextlib import nullcontext

    from services.tournament import matches as matches_mod

    tid, users = make_tournament(2)
    start(tid)
    [(room_id, players)] = open_matches(tid)

    real_t2 = finish_mod._tournament_transition_sync
    monkeypatch.setattr(finish_mod, "_tournament_transition_sync", lambda r, w: None)
    await finish_match(room_id, players, users[0])
    monkeypatch.setattr(finish_mod, "_tournament_transition_sync", real_t2)

    monkeypatch.setattr(matches_mod, "_get_tournament_lock", lambda tournament_id: nullcontext())
    monkeypatch.setattr(lifecycle, "_get_tournament_lock", lambda tournament_id: nullcontext())

    results = await asyncio.gather(
        *[asyncio.to_thread(real_t2, room_id, users[0]) for _ in range(8)],
        return_exceptions=True,
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    assert t_state(tid)["status"] == TournamentStatus.FINISHED
    assert stats(users[0])["rating"] == BASE + WIN + 2 * REWARD, "reward faqat bir marta"

"""
SQLite 기반 가상 포트폴리오(페이퍼 트레이딩) 저장소

테이블
- account           : 가상 현금 잔고 (단일 행)
- positions         : 현재 보유 중인 가상 포지션
- trades            : 전체 매수/매도 이력
- notification_log  : 텔레그램 알림 중복 발송 방지용 이력 (이벤트유형+대상+날짜 단위)
- app_state         : 킬 스위치 알림 발동 여부 등 단순 상태 플래그 저장
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH, INITIAL_CAPITAL


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                stop_loss_pct REAL NOT NULL,
                entry_date TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cash REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                ref_key TEXT NOT NULL,
                sent_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(event_type, ref_key, sent_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT COUNT(*) AS c FROM account").fetchone()
        if row["c"] == 0:
            conn.execute("INSERT INTO account (id, cash) VALUES (1, ?)", (INITIAL_CAPITAL,))


def get_cash() -> float:
    with get_conn() as conn:
        row = conn.execute("SELECT cash FROM account WHERE id = 1").fetchone()
        return float(row["cash"]) if row else float(INITIAL_CAPITAL)


def set_cash(value: float) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE account SET cash = ? WHERE id = 1", (value,))


def get_positions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM positions ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def buy_stock(code: str, name: str, price: float, quantity: int, stop_loss_pct: float):
    """가상 매수. 현금 부족 시 (False, 사유) 반환."""
    cost = price * quantity
    cash = get_cash()
    if cost > cash:
        return False, "현금이 부족하여 매수할 수 없습니다."

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO positions (code, name, entry_price, quantity, stop_loss_pct, entry_date) "
            "VALUES (?,?,?,?,?,?)",
            (code, name, price, quantity, stop_loss_pct, now),
        )
        conn.execute(
            "INSERT INTO trades (code, name, action, price, quantity, timestamp) VALUES (?,?,?,?,?,?)",
            (code, name, "BUY", price, quantity, now),
        )
    set_cash(cash - cost)
    return True, "매수가 완료되었습니다."


def sell_position(position_id: int, price: float):
    """가상 매도. 대상이 없으면 (False, 사유) 반환."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
        if not row:
            return False, "해당 포지션을 찾을 수 없습니다."
        proceeds = price * row["quantity"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        conn.execute(
            "INSERT INTO trades (code, name, action, price, quantity, timestamp) VALUES (?,?,?,?,?,?)",
            (row["code"], row["name"], "SELL", price, row["quantity"], now),
        )
    set_cash(get_cash() + proceeds)
    return True, "매도가 완료되었습니다."


def get_trades(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def reset_account() -> None:
    """가상계좌를 초기 상태로 리셋한다."""
    with get_conn() as conn:
        conn.execute("DELETE FROM positions")
        conn.execute("DELETE FROM trades")
        conn.execute("UPDATE account SET cash = ? WHERE id = 1", (INITIAL_CAPITAL,))


# ------------------------------------------------------------------
# 알림 중복 발송 방지 (이벤트유형 + 대상 + 날짜 단위로 하루 1회만 발송되도록 함)
# ------------------------------------------------------------------
def has_notified_today(event_type: str, ref_key: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM notification_log WHERE event_type = ? AND ref_key = ? AND sent_date = ?",
            (event_type, ref_key, today),
        ).fetchone()
        return row is not None


def mark_notified(event_type: str, ref_key: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO notification_log (event_type, ref_key, sent_date, created_at) "
                "VALUES (?,?,?,?)",
                (event_type, ref_key, today, now),
            )
        except sqlite3.IntegrityError:
            pass  # 이미 오늘 같은 이벤트를 기록한 경우(동시 호출 등) 조용히 무시한다


# ------------------------------------------------------------------
# 단순 상태 플래그 저장 (예: 킬 스위치 알림을 이미 보냈는지 여부)
# ------------------------------------------------------------------
def get_app_state(key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_app_state(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

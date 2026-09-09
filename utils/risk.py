"""
계좌 전체 리스크(킬 스위치) 판단 로직.

보유 현금과 보유 종목 평가금액을 합산해 계좌 전체 손실률을 계산하고,
초기 자금 대비 손실률이 KILL_SWITCH_THRESHOLD 이하로 내려가면
is_kill_switch_active=True 를 반환한다. 이 값은 대시보드 최상단 경고 배너와
신규 매수 버튼 비활성화에 함께 사용된다.
"""

from __future__ import annotations

import db
from config import INITIAL_CAPITAL, KILL_SWITCH_THRESHOLD
from utils.data_fetcher import get_stock_snapshot


def compute_account_status() -> dict:
    positions = db.get_positions()
    cash = db.get_cash()
    market_value = 0.0

    for pos in positions:
        snap = get_stock_snapshot(pos["code"], pos["name"])
        price = snap["price"] if snap["available"] else pos["entry_price"]
        market_value += price * pos["quantity"]

    total_equity = cash + market_value
    total_return_pct = (total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    is_kill_switch_active = total_return_pct <= KILL_SWITCH_THRESHOLD * 100

    return {
        "cash": cash,
        "market_value": market_value,
        "total_equity": total_equity,
        "total_return_pct": total_return_pct,
        "is_kill_switch_active": is_kill_switch_active,
        "position_count": len(positions),
    }

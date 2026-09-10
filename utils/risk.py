"""
계좌 전체 리스크(킬 스위치) 판단 로직 + 시장 위험도 경보(변동성 타겟팅) 로직.

1) 계좌 킬 스위치
   보유 현금과 보유 종목 평가금액을 합산해 계좌 전체 손실률을 계산하고,
   초기 자금 대비 손실률이 KILL_SWITCH_THRESHOLD 이하로 내려가면
   is_kill_switch_active=True 를 반환한다. 이 값은 대시보드 최상단 경고 배너와
   신규 매수 버튼 비활성화에 함께 사용된다.

2) 시장 위험도 경보 (동적 자산배분 / 변동성 타겟팅)
   파생상품(풋옵션) 없이도, 인버스 ETF·현금 비중 조절만으로 방어할 수 있도록
   KOSPI와 S&P500(국내 상장 ETF 프록시)의 20/60일 이동평균 추세 및 20일 연환산
   변동성을 분석해 정상/주의/위험 3단계로 경보하고, 단계별 권장 문구를 반환한다.

   ⚠️ KIS 국내지수 조회 API는 국내 지수만 제공하므로, S&P500은 실제 해외지수 대신
      국내 상장 ETF 'TIGER 미국S&P500'(config.SP500_PROXY_ETF)의 원화 기준 가격
      흐름으로 대체 판단한다. 환율 변동 등으로 실제 S&P500 지수 등락률과 다소
      차이가 날 수 있다. 임계값(VOL_CAUTION_THRESHOLD 등)은 조정 가능한 휴리스틱
      기준이며 절대적인 정답이 아니다.
"""

from __future__ import annotations

from typing import Optional

import db
from config import (
    INITIAL_CAPITAL,
    KILL_SWITCH_THRESHOLD,
    MA_LONG_DAYS,
    MA_SHORT_DAYS,
    SP500_PROXY_ETF,
    VOL_CAUTION_THRESHOLD,
    VOL_DANGER_THRESHOLD,
    VOLATILITY_LOOKBACK_DAYS,
)
from utils.data_fetcher import (
    get_index_daily_closes,
    get_index_snapshot,
    get_stock_daily_closes,
    get_stock_snapshot,
)


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


# ------------------------------------------------------------------
# 시장 위험도 경보 (변동성 타겟팅)
# ------------------------------------------------------------------
def _calc_moving_average(closes: list, window: int) -> Optional[float]:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _calc_annualized_volatility(closes: list, lookback: int) -> Optional[float]:
    """일별 수익률의 표준편차를 연환산(√252)한 변동성을 계산한다."""
    if len(closes) < lookback + 1:
        return None
    recent = closes[-(lookback + 1):]
    returns = []
    for i in range(1, len(recent)):
        prev = recent[i - 1]
        if prev:
            returns.append((recent[i] - prev) / prev)
    if not returns:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return (variance ** 0.5) * (252 ** 0.5)


def _assess_regime(name: str, closes: list, current_price: Optional[float]) -> dict:
    """
    20/60일 이동평균 추세와 20일 연환산 변동성을 결합해 개별 지수/ETF의
    위험도를 정상/주의/위험 3단계로 판정한다.
    """
    if not closes or current_price is None:
        return {"name": name, "available": False, "level": None}

    ma_short = _calc_moving_average(closes, MA_SHORT_DAYS)
    ma_long = _calc_moving_average(closes, MA_LONG_DAYS)
    volatility = _calc_annualized_volatility(closes, VOLATILITY_LOOKBACK_DAYS)

    # 추세: 단기선 아래이면서 단기선이 장기선보다 낮은 데드크로스 상태면 "위험"
    trend_danger = (
        ma_short is not None
        and ma_long is not None
        and current_price < ma_short
        and ma_short < ma_long
    )
    trend_caution = (not trend_danger) and ma_short is not None and current_price < ma_short

    vol_danger = volatility is not None and volatility >= VOL_DANGER_THRESHOLD
    vol_caution = (not vol_danger) and volatility is not None and volatility >= VOL_CAUTION_THRESHOLD

    if trend_danger or vol_danger:
        level = "위험"
    elif trend_caution or vol_caution:
        level = "주의"
    else:
        level = "정상"

    return {
        "name": name,
        "available": True,
        "level": level,
        "current_price": current_price,
        "ma_short": ma_short,
        "ma_long": ma_long,
        "volatility": volatility,
    }


_GUIDANCE_MAP = {
    "정상": "현금/인버스 비중 0% (주식 100% 권장)",
    "주의": "시장 변동성 증가: 현금 또는 인버스 ETF 비중 20~30% 확보 추천",
    "위험": "하락추세 진입: KODEX 200선물인버스2X 비중 확대 권장",
}


def compute_market_risk_alert() -> dict:
    """
    KOSPI와 S&P500(ETF 프록시)의 위험도를 각각 판정한 뒤, 더 위험한 쪽을 기준으로
    전체 경보 단계와 권장 문구를 결정한다. 둘 다 판단 불가(available=False)이면
    overall_level=None을 반환한다.
    """
    kospi_hist = get_index_daily_closes("KOSPI")
    kospi_snap = get_index_snapshot("KOSPI")
    kospi_closes = kospi_hist.get("closes") if kospi_hist.get("available") else []
    kospi_current = kospi_snap.get("current") if kospi_snap.get("available") else None
    kospi_regime = _assess_regime("KOSPI", kospi_closes, kospi_current)

    sp500_name, sp500_code = SP500_PROXY_ETF
    sp500_hist = get_stock_daily_closes(sp500_code)
    sp500_snap = get_stock_snapshot(sp500_code, sp500_name)
    sp500_closes = sp500_hist.get("closes") if sp500_hist.get("available") else []
    sp500_current = sp500_snap.get("price") if sp500_snap.get("available") else None
    sp500_regime = _assess_regime(sp500_name, sp500_closes, sp500_current)

    levels = [r["level"] for r in (kospi_regime, sp500_regime) if r.get("available") and r.get("level")]
    if "위험" in levels:
        overall_level = "위험"
    elif "주의" in levels:
        overall_level = "주의"
    elif levels:
        overall_level = "정상"
    else:
        overall_level = None

    return {
        "overall_level": overall_level,
        "guidance": _GUIDANCE_MAP.get(overall_level),
        "kospi": kospi_regime,
        "sp500_proxy": sp500_regime,
    }


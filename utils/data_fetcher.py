"""
시세 / 지수 / 펀더멘털 데이터 수집 모듈
- 지수/종목: 한국투자증권(KIS) Open API 전용
- 원/달러 환율: 네이버 금융 전용 (utils/naver_fx.py) — 불확실한 KIS 환율 tr_id 의존성 회피

- FinanceDataReader, yfinance, pykrx, 목업(Mock) 데이터를 전혀 사용하지 않는다.
- 모든 원시(raw) 조회는 30초 TTL로 캐싱하여 API 호출 빈도를 제한한다 (Rate Limit 방지).
  UI 렌더링 로직과 실제 KIS 호출을 이 캐시 계층으로 분리해, 화면을 다시 그릴 때마다
  API를 재호출하지 않도록 한다.
- 원시 조회 함수 자체가 예외를 삼키고 {"ok": bool, ...} 형태로 반환하므로, 실패도 함께
  캐싱되어 30초 동안은 재시도하지 않는다 (장애 시 API를 계속 두드리지 않도록 함).
- 조회가 실패하면, 직전에 성공적으로 받아온 '진짜' 시세를 st.session_state에서 꺼내
  보여주고 경고 라벨을 함께 반환한다 (가짜 데이터로 대체하지 않음).
- 실패 + 과거 성공 데이터가 전혀 없는 경우에만 "데이터 없음" 상태를 반환한다.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import utils.kis_api as kis_api
import utils.naver_fx as naver_fx
from config import KIS_INDEX_CODES, KIS_QUOTE_CACHE_TTL_SEC

STALE_WARNING = "⚠️ KIS 일시 응답 지연 (최근 성공 시세 유지 중)"


# ------------------------------------------------------------------
# Last-Known-Good 저장소 (st.session_state 기반)
# ------------------------------------------------------------------
def _lkg_key(key: str) -> str:
    return f"__kis_last_good__{key}"


def _remember_good(key: str, payload: dict) -> None:
    st.session_state[_lkg_key(key)] = {"payload": payload, "synced_at": datetime.now()}


def _recall_good(key: str) -> dict | None:
    return st.session_state.get(_lkg_key(key))


def _resolve(key: str, raw: dict) -> dict:
    """
    raw = {"ok": True, "data": {...}} 또는 {"ok": False, "error": "..."}
    -> {"available", "is_live", "warning", "synced_at", **data}
    """
    if raw.get("ok"):
        _remember_good(key, raw["data"])
        return {
            "available": True,
            "is_live": True,
            "warning": None,
            "synced_at": datetime.now(),
            **raw["data"],
        }

    cached = _recall_good(key)
    if cached is not None:
        return {
            "available": True,
            "is_live": False,
            "warning": STALE_WARNING,
            "synced_at": cached["synced_at"],
            **cached["payload"],
        }

    return {
        "available": False,
        "is_live": False,
        "warning": raw.get("error", "알 수 없는 오류"),
        "synced_at": None,
    }


# ------------------------------------------------------------------
# 원시(raw) 조회 — 캐싱 대상. 실패도 함께 캐싱해 15초간 재시도를 막는다.
# ------------------------------------------------------------------
@st.cache_data(ttl=KIS_QUOTE_CACHE_TTL_SEC, show_spinner=False)
def _raw_index_price(index_code: str) -> dict:
    try:
        data = kis_api.get_domestic_index_price(index_code)
        kis_api.throttle()
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@st.cache_data(ttl=KIS_QUOTE_CACHE_TTL_SEC * 4, show_spinner=False)
def _raw_index_daily_history(index_code: str) -> dict:
    try:
        closes = kis_api.get_domestic_index_daily_history(index_code, target_days=200)
        return {"ok": True, "data": {"closes": closes}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@st.cache_data(ttl=KIS_QUOTE_CACHE_TTL_SEC, show_spinner=False)
def _raw_stock_price(code: str) -> dict:
    try:
        data = kis_api.get_domestic_stock_price(code)
        kis_api.throttle()
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@st.cache_data(ttl=KIS_QUOTE_CACHE_TTL_SEC * 4, show_spinner=False)
def _raw_stock_daily_history(code: str) -> dict:
    try:
        # target_days=65: RSI(14) 계산뿐 아니라 60일 이동평균(시장 위험도 경보)에도
        # 재사용할 수 있도록 여유 있게 조회한다.
        closes = kis_api.get_domestic_stock_daily_history(code, target_days=65)
        kis_api.throttle()
        return {"ok": True, "data": {"closes": closes}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@st.cache_data(ttl=KIS_QUOTE_CACHE_TTL_SEC, show_spinner=False)
def _raw_fx_price() -> dict:
    """환율은 KIS가 아닌 네이버 금융에서 조회한다 (불확실한 KIS 환율 tr_id 의존성 회피)."""
    try:
        data = naver_fx.get_usd_krw_rate()
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ------------------------------------------------------------------
# 지수 스냅샷 (200일 이동평균 기반 국면 판단 포함)
# ------------------------------------------------------------------
def get_index_snapshot(name: str) -> dict:
    index_code = KIS_INDEX_CODES[name]

    price_result = _resolve(f"index_price_{index_code}", _raw_index_price(index_code))
    if not price_result["available"]:
        return {"name": name, **price_result}

    history_result = _resolve(f"index_hist_{index_code}", _raw_index_daily_history(index_code))
    closes = history_result.get("closes") if history_result.get("available") else None

    regime = None
    ma200 = None
    if closes and len(closes) >= 20:
        series = pd.Series(closes)
        ma200 = float(series.rolling(window=min(200, len(series)), min_periods=20).mean().iloc[-1])
        regime = "공격" if price_result["price"] >= ma200 else "방어"

    return {
        "name": name,
        "available": True,
        "is_live": price_result["is_live"],
        "warning": price_result["warning"],
        "synced_at": price_result["synced_at"],
        "current": price_result["price"],
        "change_pct": price_result["change_pct"],
        "ma200": ma200,
        "regime": regime,
        "regime_unavailable": ma200 is None,
    }


# ------------------------------------------------------------------
# 환율 스냅샷
# ------------------------------------------------------------------
def get_fx_snapshot() -> dict:
    result = _resolve("fx_usdkrw", _raw_fx_price())
    return result


# ------------------------------------------------------------------
# 개별 종목 스냅샷 (현재가/등락률/PER/PBR)
# ------------------------------------------------------------------
def get_stock_snapshot(code: str, name: str) -> dict:
    result = _resolve(f"stock_price_{code}", _raw_stock_price(code))
    return {"code": code, "name": name, **result}


# ------------------------------------------------------------------
# 종목 RSI (스크리너 전용)
# ------------------------------------------------------------------
def get_stock_rsi(code: str) -> dict:
    result = _resolve(f"stock_hist_{code}", _raw_stock_daily_history(code))
    if not result["available"]:
        return {"available": False, "rsi": None, "is_live": False, "warning": result["warning"]}

    closes = result.get("closes") or []
    rsi = calc_rsi(pd.Series(closes)) if closes else None
    return {
        "available": rsi is not None,
        "rsi": rsi,
        "is_live": result["is_live"],
        "warning": result["warning"],
    }


# ------------------------------------------------------------------
# 일자별 종가 히스토리 재사용 노출 함수
# (200일 이동평균/RSI 계산에 쓰던 원시 캐시를 그대로 재사용하므로 추가 API 호출이 없다.
#  utils/risk.py 의 시장 위험도 경보(20/60일 이동평균, 20일 변동성)에서 사용한다.)
# ------------------------------------------------------------------
def get_index_daily_closes(name: str) -> dict:
    index_code = KIS_INDEX_CODES[name]
    return _resolve(f"index_hist_{index_code}", _raw_index_daily_history(index_code))


def get_stock_daily_closes(code: str) -> dict:
    return _resolve(f"stock_hist_{code}", _raw_stock_daily_history(code))


# ------------------------------------------------------------------
# RSI 계산 (순수 계산 로직 — 외부 데이터 소스 아님)
# ------------------------------------------------------------------
def calc_rsi(close: pd.Series, period: int = 14) -> float | None:
    if close is None or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    last = rsi.iloc[-1]
    return float(last) if pd.notna(last) else None

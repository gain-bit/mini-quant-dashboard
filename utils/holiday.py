"""
한국거래소(KRX) 휴장일 캘린더 연동.

KIS Open API의 '국내휴장일조회'(tr_id CTCA0903R)를 사용하며, 기존에 설정한
KIS APP_KEY/APP_SECRET을 그대로 재사용하므로 별도의 API 키를 새로 발급받을 필요가 없다.

- 조회 결과는 날짜(YYYYMMDD) 단위로 캐싱해 같은 날에는 반복 호출하지 않는다.
- 조회가 실패하거나 KIS 키가 아직 설정되지 않은 경우, "휴장일 여부를 알 수 없음"으로
  간주해 요일/시간 조건만으로 장중 여부를 판단하도록 fail-open 처리한다
  (휴장일 API 장애 때문에 정상 거래일에 자동 새로고침이 멈추는 사고를 방지하기 위함).
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

import utils.kis_api as kis_api

HOLIDAY_CACHE_TTL_SEC = 6 * 60 * 60  # 6시간 (하루 중 여러 번 호출해도 사실상 1회만 실제 조회)


@st.cache_data(ttl=HOLIDAY_CACHE_TTL_SEC, show_spinner=False)
def _raw_holiday_status(date_str: str) -> dict:
    try:
        is_trading_day = kis_api.get_domestic_holiday_status(date_str)
        return {"ok": True, "is_trading_day": is_trading_day}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def is_holiday(dt: datetime) -> bool | None:
    """
    dt(KST datetime) 기준으로 해당 날짜가 한국거래소 휴장일인지 조회한다.

    반환:
      True  -> 휴장일로 확인됨 (공휴일/임시공휴일 등)
      False -> 개장일로 확인됨
      None  -> 조회 불가(키 미설정/API 오류) — 호출부에서 fail-open으로 처리할 것
    """
    if not kis_api.is_configured():
        return None

    date_str = dt.strftime("%Y%m%d")
    raw = _raw_holiday_status(date_str)
    if not raw["ok"]:
        return None
    return not raw["is_trading_day"]

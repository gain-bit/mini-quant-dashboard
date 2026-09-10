"""
네이버 금융에서 원/달러(USD/KRW) 환율을 가져오는 전용 모듈.

KIS Open API의 환율 조회 tr_id/엔드포인트는 문서 버전에 따른 불확실성이 커서,
환율만은 네이버 금융의 공개 데이터를 사용하도록 분리했다.

조회 우선순위:
  1) 네이버 증권 마켓인덱스 JSON API (api.stock.naver.com)
  2) 네이버 금융 환율 페이지 HTML 파싱 (finance.naver.com/marketindex) — JSON 실패 시 폴백

⚠️ 둘 다 네이버 측이 공식적으로 제공을 보증하는 API가 아니라, 페이지/응답 구조가
   사전 고지 없이 바뀔 수 있다. 장애가 지속되면 최신 구조에 맞춰 파서를 갱신할 것.
   (상위 계층인 utils/data_fetcher.py 에서 실패 시 Last-Known-Good 폴백을 처리하므로,
    이 모듈이 실패하더라도 화면에는 마지막 성공 환율이 경고와 함께 표시된다.)
"""

from __future__ import annotations

import re

import requests

_JSON_URL = "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"
_HTML_URL = "https://finance.naver.com/marketindex/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MiniQuantDashboard/1.0; +https://streamlit.io)"}
_TIMEOUT_SEC = 5


class NaverFXError(Exception):
    """네이버 환율 조회가 모든 방법(JSON/HTML)으로 실패했을 때 발생."""


def _to_float(value) -> float:
    if value is None or value == "":
        raise ValueError("빈 값입니다.")
    s = str(value).replace(",", "").replace("+", "").strip()
    return float(s)


def _first_present(data: dict, keys: list[str]):
    for k in keys:
        if k in data and data[k] not in (None, ""):
            return data[k]
    return None


# ------------------------------------------------------------------
# 1차: 네이버 증권 마켓인덱스 JSON API
# ------------------------------------------------------------------
def _fetch_via_json() -> dict:
    resp = requests.get(_JSON_URL, headers=_HEADERS, timeout=_TIMEOUT_SEC)
    resp.raise_for_status()
    data = resp.json()

    # 실제 응답은 필드가 최상위가 아니라 "exchangeInfo" 키 안에 중첩되어 내려온다.
    # (예: {"exchangeInfo": {"closePrice": "1,345.30", "fluctuationsType": {...}, ...}})
    # exchangeInfo가 없는 스키마 변형도 대비해 없으면 최상위 데이터를 그대로 사용한다.
    info = data.get("exchangeInfo", data) if isinstance(data, dict) else {}
    if not isinstance(info, dict):
        info = {}

    # 네이버 응답 스키마는 버전에 따라 필드명이 조금씩 다를 수 있어 후보 키를 순서대로 탐색한다.
    raw_price = _first_present(info, ["closePrice", "closePriceRaw", "price", "nv"])
    if raw_price is None:
        raise NaverFXError(f"JSON 응답에서 가격 필드를 찾을 수 없습니다: {data}")
    price = _to_float(raw_price)

    raw_change_pct = _first_present(
        info, ["fluctuationsRatio", "changeRate", "fluctuationRatio", "cr"]
    )
    change_pct = _to_float(raw_change_pct) if raw_change_pct is not None else 0.0

    # 등락 방향은 문자열이 아니라 {"code": "2", "text": "상승", "name": "RISING"} 형태의
    # 딕셔너리(fluctuationsType)로 내려온다. "상승/RISING"이면 양수, "하락/FALLING"이면 음수로
    # 부호를 맞춘다. 코드 값("1"/"2" 등)은 스키마 버전에 따라 바뀔 수 있어 text/name으로 판단한다.
    fluct_type = info.get("fluctuationsType")
    if isinstance(fluct_type, dict):
        direction = str(fluct_type.get("name") or fluct_type.get("text") or "").upper()
    else:
        direction = str(fluct_type or "").upper()

    if direction in ("FALLING", "DOWN", "하락", "DEC", "DECLINING"):
        change_pct = -abs(change_pct)
    elif direction in ("RISING", "UP", "상승", "INC", "INCREASING"):
        change_pct = abs(change_pct)
    # 방향을 판단할 수 없으면 원본 부호(대개 절대값)를 그대로 둔다.

    return {"price": price, "change_pct": change_pct}


# ------------------------------------------------------------------
# 2차: 네이버 금융 환율 페이지 HTML 파싱 (JSON 실패 시 폴백)
# ------------------------------------------------------------------
def _fetch_via_html() -> dict:
    resp = requests.get(_HTML_URL, headers=_HEADERS, timeout=_TIMEOUT_SEC)
    resp.raise_for_status()
    html = resp.text

    # finance.naver.com/marketindex/ 페이지의 미국 USD 항목(첫 번째 환율 카드) 구조를 파싱한다.
    # 방향 클래스(point_up / point_dn)와 현재가(value), 변동폭(change)을 추출한다.
    block_match = re.search(
        r'class="head_info[^"]*point_(up|dn)"[^>]*>\s*<span class="value">([\d,.]+)</span>',
        html,
    )
    if not block_match:
        raise NaverFXError("HTML에서 환율 값을 찾을 수 없습니다 (페이지 구조 변경 가능성).")

    direction = block_match.group(1)
    price = _to_float(block_match.group(2))

    change_match = re.search(r'<span class="change">([\d,.]+)</span>', html)
    change = _to_float(change_match.group(1)) if change_match else 0.0

    change_pct = (change / price * 100) if price else 0.0
    change_pct = -abs(change_pct) if direction == "dn" else abs(change_pct)

    return {"price": price, "change_pct": change_pct}


def get_usd_krw_rate() -> dict:
    """
    원/달러 환율을 조회한다. JSON API를 우선 시도하고 실패하면 HTML 페이지를 파싱한다.
    둘 다 실패하면 NaverFXError를 던진다 (상위 계층에서 Last-Known-Good 처리).
    반환: {"price": float, "change_pct": float}
    """
    try:
        return _fetch_via_json()
    except Exception as json_err:
        try:
            return _fetch_via_html()
        except Exception as html_err:
            raise NaverFXError(
                f"네이버 환율 조회 실패 (JSON: {json_err} / HTML: {html_err})"
            ) from html_err

"""
한국투자증권(KIS) Open API REST 클라이언트

- .streamlit/secrets.toml 의 [kis] 섹션에서 인증 정보를 읽어온다.
- Access Token은 프로세스 메모리(전역 캐시)에 저장하고, 만료되거나 401 응답을
  받으면 자동으로 재발급받는다. (세션마다 재발급하면 KIS의 발급 빈도 제한에
  걸리기 쉬우므로, 앱 프로세스 전체가 토큰 1개를 공유하도록 설계했다.)
- 메모리 캐시와 별개로, 발급된 토큰을 .streamlit/kis_token_cache.json 파일에도
  저장한다. 개발 중 코드 수정으로 Streamlit 프로세스가 재시작되더라도 아직 유효한
  토큰이 남아있으면 그것을 그대로 재사용해, KIS의 "토큰 재발급 1분당 1회" 제한
  (에러코드 EGW00133)에 걸리지 않도록 하기 위함이다.
- 모든 GET 요청은 공통 `_request()`를 거치며, 네트워크 오류/HTTP 오류/KIS 응답
  오류(rt_cd != "0")를 KISAPIError 로 통일해서 던진다. "초당 거래건수 초과"(EGW00201)
  오류는 1.0초 대기 후 최대 2회까지 자동 재시도한다. 상위 계층(data_fetcher)에서
  이 예외를 잡아 Last-Known-Good 폴백 처리를 한다.

⚠️ 참고: 지수/종목 "현재가" 조회(FHPUP02100000, FHKST01010100)는 KIS Open API에서
가장 널리 쓰이는 표준 엔드포인트라 안정적이다. 일자별 히스토리(200일 이평/RSI용)의
tr_id/파라미터/응답 필드명은 KIS 문서 개정 가능성이 있어 여러 후보 필드명을 시도하는
방어적 파싱을 적용했다. 원/달러 환율은 KIS가 아닌 네이버 금융(utils/naver_fx.py)에서
조회한다 (불확실한 KIS 환율 tr_id 의존성을 피하기 위함).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta

import requests
import streamlit as st

from config import (
    KIS_BASE_URL_REAL,
    KIS_BASE_URL_VIRTUAL,
    KIS_RATE_LIMIT_MAX_RETRIES,
    KIS_RATE_LIMIT_MSG_CODE,
    KIS_RATE_LIMIT_RETRY_DELAY_SEC,
    KIS_REQUEST_DELAY_SEC,
    KIS_REQUEST_TIMEOUT_SEC,
    KIS_TOKEN_CACHE_PATH,
    KIS_TR_ID,
)

# ------------------------------------------------------------------
# 토큰 캐시: 프로세스 전역(세션 간 공유, 락으로 동시 재발급 방지) + 로컬 파일 백업
# (파일 백업은 프로세스 재시작 시에도 유효한 토큰을 재사용하기 위함)
# ------------------------------------------------------------------
_token_lock = threading.Lock()
_TOKEN_CACHE: dict = {"access_token": None, "expires_at": None}
_file_load_attempted = False  # 프로세스당 파일 로드는 1회만 시도한다


class KISConfigError(Exception):
    """secrets.toml에 KIS 인증 정보가 없거나 불완전할 때 발생."""


class KISAPIError(Exception):
    """네트워크 오류, HTTP 오류, KIS 응답 오류(rt_cd != 0) 등 API 호출 실패 시 발생."""


# ------------------------------------------------------------------
# 인증 정보 로딩
# ------------------------------------------------------------------
def _load_secrets() -> dict:
    try:
        kis_secrets = st.secrets["kis"]
    except Exception as e:
        raise KISConfigError(
            "⚠️ .streamlit/secrets.toml 파일에 한국투자증권 API Key를 설정해주세요."
        ) from e

    required = ["APP_KEY", "APP_SECRET", "CANO", "ACNT_PRDT_CD"]
    missing = [k for k in required if not str(kis_secrets.get(k, "")).strip()]
    if missing:
        raise KISConfigError(
            "⚠️ .streamlit/secrets.toml 파일에 한국투자증권 API Key를 설정해주세요. "
            f"(누락된 항목: {', '.join(missing)})"
        )
    return dict(kis_secrets)


def is_configured() -> bool:
    """[kis] 시크릿이 정상적으로 설정되어 있는지 확인한다. 앱이 죽지 않도록 예외를 여기서 흡수."""
    try:
        _load_secrets()
        return True
    except KISConfigError:
        return False


def get_config_error_message() -> str | None:
    try:
        _load_secrets()
        return None
    except KISConfigError as e:
        return str(e)


def get_base_url() -> str:
    secrets = _load_secrets()
    is_virtual = bool(secrets.get("IS_VIRTUAL", False))
    return KIS_BASE_URL_VIRTUAL if is_virtual else KIS_BASE_URL_REAL


# ------------------------------------------------------------------
# 로컬 파일 기반 토큰 캐시
# (프로세스가 재시작되어도 아직 유효한 토큰을 재사용해 1분당 1회 재발급 제한 회피)
# ------------------------------------------------------------------
def _token_fingerprint(secrets: dict) -> str:
    """캐시 파일의 토큰이 지금 secrets.toml 설정과 같은 계정/모드인지 확인하기 위한 식별자."""
    return f"{secrets.get('APP_KEY', '')}:{bool(secrets.get('IS_VIRTUAL', False))}"


def _load_token_from_file() -> None:
    """
    디스크에 저장된 토큰 캐시를 읽어, 아직 유효하고 현재 secrets 설정과 일치할 때만
    메모리 캐시에 반영한다. 파일이 없거나 읽기/파싱에 실패해도 조용히 넘어간다
    (이 경우 평소처럼 새로 토큰을 발급받는다).
    """
    try:
        if not KIS_TOKEN_CACHE_PATH.exists():
            return
        raw = json.loads(KIS_TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
        secrets = _load_secrets()
    except Exception:
        return

    if raw.get("fingerprint") != _token_fingerprint(secrets):
        return  # 다른 APP_KEY/모의-실전 전환 등으로 설정이 바뀐 경우 재사용하지 않는다

    token = raw.get("access_token")
    expires_at_str = raw.get("expires_at")
    if not token or not expires_at_str:
        return

    try:
        expires_at = datetime.fromisoformat(expires_at_str)
    except ValueError:
        return

    if datetime.now() < expires_at:
        _TOKEN_CACHE["access_token"] = token
        _TOKEN_CACHE["expires_at"] = expires_at


def _save_token_to_file(secrets: dict) -> None:
    """메모리에 있는 최신 토큰을 디스크에도 저장한다. 저장 실패는 치명적이지 않으므로 무시한다."""
    try:
        KIS_TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": _TOKEN_CACHE["access_token"],
            "expires_at": _TOKEN_CACHE["expires_at"].isoformat(),
            "fingerprint": _token_fingerprint(secrets),
        }
        KIS_TOKEN_CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------------
# Access Token 발급 / 캐싱 / 자동 재발급
# ------------------------------------------------------------------
def _issue_access_token() -> str:
    secrets = _load_secrets()
    url = f"{get_base_url()}/oauth2/tokenP"
    payload = {
        "grant_type": "client_credentials",
        "appkey": secrets["APP_KEY"],
        "appsecret": secrets["APP_SECRET"],
    }

    try:
        resp = requests.post(url, json=payload, timeout=KIS_REQUEST_TIMEOUT_SEC)
    except requests.exceptions.RequestException as e:
        raise KISAPIError(f"토큰 발급 네트워크 오류: {e}") from e

    if resp.status_code != 200:
        raise KISAPIError(f"토큰 발급 실패 (HTTP {resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    token = data.get("access_token")
    expires_in = int(data.get("expires_in", 86400))
    if not token:
        raise KISAPIError(f"토큰 발급 응답에 access_token이 없습니다: {data}")

    # 만료 5분 전에 미리 갱신되도록 안전마진을 둔다.
    expires_at = datetime.now() + timedelta(seconds=max(expires_in - 300, 60))
    _TOKEN_CACHE["access_token"] = token
    _TOKEN_CACHE["expires_at"] = expires_at
    _save_token_to_file(secrets)
    return token


def get_access_token(force_refresh: bool = False) -> str:
    """
    프로세스 메모리에 캐싱된 Access Token을 반환한다.
    메모리 캐시가 비어 있으면(예: 프로세스 재시작 직후) 먼저 로컬 파일 캐시에서
    아직 유효한 토큰이 있는지 확인해 재사용을 시도한다.
    그래도 없거나 만료되었거나 force_refresh=True 이면 새로 발급받는다 (401 대응 포함).
    """
    global _file_load_attempted
    with _token_lock:
        if _TOKEN_CACHE.get("access_token") is None and not _file_load_attempted:
            _file_load_attempted = True
            _load_token_from_file()

        token = _TOKEN_CACHE.get("access_token")
        expires_at = _TOKEN_CACHE.get("expires_at")
        needs_refresh = (
            force_refresh or token is None or expires_at is None or datetime.now() >= expires_at
        )
        if needs_refresh:
            return _issue_access_token()
        return token


# ------------------------------------------------------------------
# 공통 REST 요청 처리
# ------------------------------------------------------------------
def _build_headers(tr_id: str, secrets: dict, token: str) -> dict:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": secrets["APP_KEY"],
        "appsecret": secrets["APP_SECRET"],
        "tr_id": tr_id,
        "custtype": "P",
    }


def _request(
    path: str,
    tr_id: str,
    params: dict,
    retry_on_401: bool = True,
    rate_limit_retries: int = KIS_RATE_LIMIT_MAX_RETRIES,
) -> dict:
    """
    KIS REST GET 요청 공통 처리.
    - 401(토큰 만료 추정) 발생 시 토큰을 강제로 한 번 재발급받아 재시도한다.
    - "초당 거래건수를 초과하였습니다"(msg_cd=EGW00201) 오류는 KIS가 HTTP 200이 아닌
      상태코드(주로 500)로 내려보내는 경우가 있어, HTTP 상태코드를 판단하기 전에 먼저
      응답 바디에서 이 오류코드를 확인한다. 감지되면 1.0초 대기 후 최대 2회까지 자동
      재시도하고, 그래도 실패하면 KISAPIError를 던진다(상위 계층이 Last-Known-Good으로
      폴백한다).
    - 그 외 네트워크 오류/타임아웃/HTTP 오류/KIS 응답 오류는 모두 KISAPIError로 통일한다.
    """
    secrets = _load_secrets()
    token = get_access_token()
    url = f"{get_base_url()}{path}"
    headers = _build_headers(tr_id, secrets, token)

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=KIS_REQUEST_TIMEOUT_SEC)
    except requests.exceptions.RequestException as e:
        raise KISAPIError(f"네트워크 오류(연결 실패/타임아웃): {e}") from e

    if resp.status_code == 401 and retry_on_401:
        get_access_token(force_refresh=True)
        return _request(path, tr_id, params, retry_on_401=False, rate_limit_retries=rate_limit_retries)

    # 상태코드와 무관하게 응답 바디를 먼저 파싱해 Rate Limit(EGW00201) 여부를 확인한다.
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None

    msg_cd = parsed.get("msg_cd") if isinstance(parsed, dict) else None
    if msg_cd == KIS_RATE_LIMIT_MSG_CODE:
        if rate_limit_retries > 0:
            time.sleep(KIS_RATE_LIMIT_RETRY_DELAY_SEC)
            return _request(
                path,
                tr_id,
                params,
                retry_on_401=retry_on_401,
                rate_limit_retries=rate_limit_retries - 1,
            )
        raise KISAPIError(
            f"초당 거래건수 초과(EGW00201) — {KIS_RATE_LIMIT_MAX_RETRIES}회 재시도 후에도 실패했습니다."
        )

    if resp.status_code != 200:
        raise KISAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    if not isinstance(parsed, dict):
        raise KISAPIError("응답을 JSON으로 해석할 수 없습니다.")

    rt_cd = parsed.get("rt_cd")
    if rt_cd is not None and rt_cd != "0":
        raise KISAPIError(f"KIS API 오류(rt_cd={rt_cd}): {parsed.get('msg1', '알 수 없는 오류')}")

    return parsed


def throttle() -> None:
    """연속 호출 시 호출 간 지연을 준다 (Rate Limit / IP 차단 방지)."""
    time.sleep(KIS_REQUEST_DELAY_SEC)


# ------------------------------------------------------------------
# 국내 지수 현재가 (국내업종 현재지수)
# ------------------------------------------------------------------
def get_domestic_index_price(index_code: str) -> dict:
    """index_code: '0001'(코스피) / '1001'(코스닥) -> {"price": float, "change_pct": float}"""
    data = _request(
        path=KIS_TR_ID["index_price_path"],
        tr_id=KIS_TR_ID["index_price"],
        params={"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": index_code},
    )
    output = data.get("output", {})
    price = float(output.get("bstp_nmix_prpr", 0) or 0)
    change_pct = float(output.get("bstp_nmix_prdy_ctrt", 0) or 0)
    if price <= 0:
        raise KISAPIError("지수 응답에서 유효한 가격을 찾을 수 없습니다.")
    return {"price": price, "change_pct": change_pct}


# ------------------------------------------------------------------
# 국내 주식 현재가 (PER/PBR 포함)
# ------------------------------------------------------------------
def get_domestic_stock_price(stock_code: str) -> dict:
    """stock_code: 6자리 KRX 코드 -> {"price","change_pct","per","pbr"}"""
    data = _request(
        path=KIS_TR_ID["stock_price_path"],
        tr_id=KIS_TR_ID["stock_price"],
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code},
    )
    output = data.get("output", {})
    price = float(output.get("stck_prpr", 0) or 0)
    change_pct = float(output.get("prdy_ctrt", 0) or 0)
    if price <= 0:
        raise KISAPIError("종목 응답에서 유효한 가격을 찾을 수 없습니다.")

    def _safe_float(v):
        try:
            f = float(v)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    per = _safe_float(output.get("per"))
    pbr = _safe_float(output.get("pbr"))
    return {"price": price, "change_pct": change_pct, "per": per, "pbr": pbr}


# ------------------------------------------------------------------
# 국내업종 일자별지수 (200일 이동평균 계산용)
# ⚠️ tr_id/파라미터는 최신 KIS 공식 문서로 재확인 권장.
#    응답 필드명이 버전에 따라 다를 가능성에 대비해 후보 키를 순서대로 탐색하고,
#    행 단위로 파싱 실패를 흡수해(한 행이 깨져도 전체가 죽지 않도록) 안정성을 높였다.
# ------------------------------------------------------------------
_INDEX_CLOSE_FIELD_CANDIDATES = ["bstp_nmix_prpr", "bstp_nmix_clpr", "clpr", "prdy_clpr"]


def _extract_first_float(row: dict, keys: list[str]):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            try:
                f = float(v)
                if f > 0:
                    return f
            except (TypeError, ValueError):
                continue
    return None


def get_domestic_index_daily_history(index_code: str, target_days: int = 200) -> list[float]:
    closes: list[float] = []
    end_date = datetime.now()
    max_iterations = 6  # 1회 호출당 약 100건 내외 반환 가정, 최대 약 2~3년치까지 조회

    for _ in range(max_iterations):
        if len(closes) >= target_days:
            break
        start_date = end_date - timedelta(days=140)
        data = _request(
            path=KIS_TR_ID["index_daily_price_path"],
            tr_id=KIS_TR_ID["index_daily_price"],
            params={
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": index_code,
                "FID_INPUT_DATE_1": start_date.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
            },
        )
        rows = data.get("output2") or data.get("output") or []
        if not rows:
            break

        batch = []
        for r in rows:
            val = _extract_first_float(r, _INDEX_CLOSE_FIELD_CANDIDATES)
            if val is not None:
                batch.append(val)

        if not batch:
            # 이번 구간에서 유효한 값을 하나도 못 얻었다면 더 진행해도 의미가 없으므로 중단한다.
            break

        # 200일 이동평균은 산술평균이라 순서와 무관하게 값만 정확하면 되므로, 정렬 순서 불확실성은
        # 결과 정확도에 영향을 주지 않는다 (윈도우 크기 == 전체 길이일 때).
        closes = closes + batch
        end_date = start_date - timedelta(days=1)
        throttle()

    return closes[:target_days]


# ------------------------------------------------------------------
# 주식현재가 일자별 (RSI 계산용)
# ⚠️ tr_id/파라미터는 최신 KIS 공식 문서로 재확인 권장.
#    응답 필드명 후보를 여러 개 시도하고, 정렬 순서는 최신순으로 내려온다고 가정해
#    과거->최신 순으로 뒤집는다 (RSI는 순서에 민감하므로 이 부분이 특히 중요하다).
# ------------------------------------------------------------------
_STOCK_CLOSE_FIELD_CANDIDATES = ["stck_clpr", "stck_prpr", "clpr"]


def get_domestic_stock_daily_history(stock_code: str, target_days: int = 30) -> list[float]:
    data = _request(
        path=KIS_TR_ID["stock_daily_price_path"],
        tr_id=KIS_TR_ID["stock_daily_price"],
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",
        },
    )
    rows = data.get("output") or data.get("output2") or []

    closes = []
    for r in rows:
        val = _extract_first_float(r, _STOCK_CLOSE_FIELD_CANDIDATES)
        if val is not None:
            closes.append(val)

    if not closes:
        raise KISAPIError("일자별 시세 응답에서 유효한 종가 필드를 찾을 수 없습니다.")

    # 최신순으로 내려올 가능성이 높아 과거->최신 순으로 뒤집는다.
    closes.reverse()
    return closes[-target_days:] if len(closes) > target_days else closes


# ------------------------------------------------------------------
# 국내휴장일조회 (한국거래소 휴장일 캘린더)
# 별도의 API를 새로 발급받을 필요가 없다 — 기존 KIS APP_KEY/APP_SECRET을 그대로 재사용한다.
# ⚠️ tr_id/응답 필드명은 최신 KIS 공식 문서로 재확인 권장. 여러 후보 필드명을
#    순서대로 시도하는 방어적 파싱을 적용했다.
# ------------------------------------------------------------------
_TRADING_DAY_FIELD_CANDIDATES = ["opnd_yn", "bzdy_yn", "tr_day_yn"]


def get_domestic_holiday_status(date_str: str) -> bool:
    """
    date_str: 'YYYYMMDD' 형식의 기준일자.
    반환: True(정상 개장일) / False(휴장일 — 주말/공휴일/임시공휴일 등).
    조회 자체가 실패하면 KISAPIError를 던진다 (상위 계층에서 fail-open 처리).
    """
    data = _request(
        path="/uapi/domestic-stock/v1/quotations/chk-holiday",
        tr_id="CTCA0903R",
        params={"BASS_DT": date_str, "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
    )
    rows = data.get("output") or []
    if not rows:
        raise KISAPIError("휴장일 조회 응답이 비어 있습니다.")

    row = rows[0]
    for key in _TRADING_DAY_FIELD_CANDIDATES:
        val = row.get(key)
        if val is not None:
            return str(val).strip().upper() == "Y"

    raise KISAPIError(f"휴장일 조회 응답에서 개장일 여부 필드를 찾을 수 없습니다: {row}")

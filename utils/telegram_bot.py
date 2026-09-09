"""
텔레그램 봇 API 연동 모듈.

.streamlit/secrets.toml 의 [telegram] 섹션(BOT_TOKEN, CHAT_ID)을 사용해
실시간 푸시 알림을 전송한다. 키가 설정되어 있지 않거나 네트워크 오류가 발생해도
앱 전체가 멈추지 않도록 모든 예외를 이 모듈 안에서 흡수하고, 항상
(성공 여부, 안내/오류 메시지) 형태로만 반환한다.

텔레그램 서버 응답이 느려 requests.exceptions.ReadTimeout이 발생하는 경우는 별도로
처리한다. 이 경우 요청 자체(전송)는 이미 서버로 전달되었을 가능성이 높고 단지 응답
확인만 지연된 것이므로, 실패로 단정해 빨간 에러로 표시하지 않고 "발송되었으나 응답
확인이 지연되었다"는 안내만 반환한다.
"""

from __future__ import annotations

import requests
import streamlit as st

TELEGRAM_API_TIMEOUT_SEC = 12

TIMEOUT_NOTICE_MESSAGE = "⚠️ 메시지가 발송되었으나 응답 확인이 지연되었습니다."
SUCCESS_MESSAGE = "전송 완료"


def _load_secrets() -> dict | None:
    try:
        cfg = st.secrets["telegram"]
    except Exception:
        return None

    token = str(cfg.get("BOT_TOKEN", "")).strip()
    chat_id = str(cfg.get("CHAT_ID", "")).strip()
    if not token or not chat_id:
        return None
    return {"BOT_TOKEN": token, "CHAT_ID": chat_id}


def is_configured() -> bool:
    """[telegram] 시크릿(BOT_TOKEN, CHAT_ID)이 정상적으로 설정되어 있는지 확인한다."""
    return _load_secrets() is not None


def send_message(text: str) -> tuple[bool, str]:
    """
    텔레그램으로 메시지를 전송한다.
    반환: (성공 여부, 안내 또는 오류 메시지). 실패해도 예외를 던지지 않는다.

    ReadTimeout(응답 확인 지연)은 실패로 취급하지 않고 ok=True와 함께
    TIMEOUT_NOTICE_MESSAGE를 반환한다 — 호출부는 이 메시지를 성공 메시지와
    구분해 경고(주의) 색상 등으로 표시하는 것을 권장한다.
    """
    secrets = _load_secrets()
    if secrets is None:
        return False, "텔레그램 BOT_TOKEN/CHAT_ID가 설정되어 있지 않습니다."

    url = f"https://api.telegram.org/bot{secrets['BOT_TOKEN']}/sendMessage"
    payload = {"chat_id": secrets["CHAT_ID"], "text": text}

    try:
        resp = requests.post(url, json=payload, timeout=TELEGRAM_API_TIMEOUT_SEC)
    except requests.exceptions.ReadTimeout:
        # 요청은 전송되었으나 응답을 기다리다 시간 초과된 경우. 실패로 단정하지 않는다.
        return True, TIMEOUT_NOTICE_MESSAGE
    except requests.exceptions.RequestException as e:
        return False, f"텔레그램 전송 네트워크 오류: {e}"

    if resp.status_code != 200:
        return False, f"텔레그램 전송 실패 (HTTP {resp.status_code}): {resp.text[:200]}"

    try:
        data = resp.json()
    except ValueError:
        return False, "텔레그램 응답을 해석할 수 없습니다."

    if not data.get("ok"):
        return False, f"텔레그램 API 오류: {data.get('description', '알 수 없는 오류')}"

    return True, SUCCESS_MESSAGE

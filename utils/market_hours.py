"""
한국 주식시장 정규장 운영시간(KST) 판별 유틸.

- 월~금(0=월요일 ~ 4=금요일), 09:00:00 ~ 16:00:00 (KST) 사이만 "장중"으로 판단한다.
- 표준 라이브러리 zoneinfo("Asia/Seoul")로 타임존을 계산하므로 별도 패키지가 필요 없다.
  (일부 환경, 특히 Windows는 시스템에 IANA 타임존 DB가 없을 수 있어 requirements.txt에
   tzdata를 추가해두었다. Linux/macOS는 보통 시스템 DB가 있어 tzdata 없이도 동작한다.)
- 공휴일(설/추석/임시공휴일 등)은 반영하지 않는다 — 요일/시간 조건만으로 판단한다.
  필요 시 한국거래소 휴장일 캘린더를 별도로 연동해 개선할 수 있다.
"""

from __future__ import annotations

from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9 미만 대비
    ZoneInfo = None

from config import MARKET_CLOSE_TIME, MARKET_OPEN_TIME, MARKET_TIMEZONE

_KST = ZoneInfo(MARKET_TIMEZONE) if ZoneInfo is not None else None


def now_kst() -> datetime:
    """현재 시각을 KST(Asia/Seoul) 기준으로 반환한다."""
    if _KST is not None:
        return datetime.now(_KST)
    # zoneinfo를 전혀 쓸 수 없는 예외적인 환경에서는 로컬 시간을 그대로 사용한다.
    # (서버가 KST가 아닌 경우 판단이 부정확할 수 있으니 Python 3.9+ 환경 사용을 권장)
    return datetime.now()


def is_market_open(dt: datetime | None = None) -> bool:
    """
    주어진 시각(기본: 현재 KST)이 정규장 운영시간(월~금 09:00:00~16:00:00 KST)인지 판단한다.
    """
    dt = dt or now_kst()
    if dt.weekday() >= 5:  # 5=토요일, 6=일요일
        return False
    return MARKET_OPEN_TIME <= dt.time() < MARKET_CLOSE_TIME

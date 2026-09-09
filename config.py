"""
전역 설정 및 상수 모음
- 페이퍼 트레이딩 파라미터
- 한국투자증권(KIS) Open API 설정 (엔드포인트/tr_id/캐시·지연 정책)
- 장 운영시간(KST) 및 자동 새로고침 정책
- 8대 섹터 대표주 유니버스
"""

from datetime import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# ------------------------------------------------------------------
# 페이퍼 트레이딩 / 리스크 파라미터
# ------------------------------------------------------------------
INITIAL_CAPITAL = 50_000_000          # 가상 초기 자금 5,000만원
KILL_SWITCH_THRESHOLD = -0.02         # 계좌 전체 손실률 -2% 도달 시 킬 스위치
DEFAULT_STOP_LOSS_LEVELS = [-0.03, -0.05]   # 목표 손절가 옵션 (-3%, -5%)

DB_PATH = "quant_dashboard.db"

# 토큰 캐시 파일: 프로세스가 재시작되어도(예: 코드 수정 후 재실행) 아직 유효한 토큰을
# 재사용해 KIS의 "토큰 재발급 1분당 1회" 제한(EGW00133)에 걸리지 않도록 한다.
KIS_TOKEN_CACHE_PATH = PROJECT_ROOT / ".streamlit" / "kis_token_cache.json"

# ------------------------------------------------------------------
# 장 운영시간(KST) 및 자동 새로고침 정책
# ------------------------------------------------------------------
MARKET_TIMEZONE = "Asia/Seoul"
MARKET_OPEN_TIME = time(9, 0, 0)    # 정규장 시작 (KST)
MARKET_CLOSE_TIME = time(16, 0, 0)  # 정규장 종료 (KST)
# 월~금(0~4), 09:00:00~16:00:00 (KST) 사이에만 장중으로 판단한다. 공휴일은 반영하지 않는다.

AUTOREFRESH_INTERVAL_SEC = 15   # 장중 자동 새로고침 주기 (캐시 TTL과 동일하게 맞춤)

# ------------------------------------------------------------------
# 한국투자증권(KIS) Open API 설정
# ------------------------------------------------------------------
KIS_BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"        # 실전투자
KIS_BASE_URL_VIRTUAL = "https://openapivts.koreainvestment.com:29443"  # 모의투자

KIS_REQUEST_TIMEOUT_SEC = 5     # HTTP 요청 타임아웃 (네트워크 순간 끊김 대비)
KIS_REQUEST_DELAY_SEC = 0.2     # 종목/지수 순회 조회 시 호출 간 지연 (초당 거래건수 초과 EGW00201 방지)
KIS_RATE_LIMIT_MSG_CODE = "EGW00201"   # KIS "초당 거래건수를 초과하였습니다" 오류 코드
KIS_RATE_LIMIT_RETRY_DELAY_SEC = 1.0   # 레이트리밋 감지 시 재시도 전 대기 시간
KIS_RATE_LIMIT_MAX_RETRIES = 2         # 레이트리밋 감지 시 최대 재시도 횟수
KIS_QUOTE_CACHE_TTL_SEC = 15    # 시세 캐싱 TTL (무분별한 API 호출 차단)

# tr_id 및 엔드포인트 모음
# ⚠️ 아래 중 "현재가" 계열(index_price, stock_price)은 KIS Open API에서 가장 널리 쓰이는
#    표준 엔드포인트로 안정적이다. 반면 일별 히스토리/환율 관련 tr_id·파라미터는 KIS 측
#    정책 변경 가능성이 있으므로, 실제 배포 전 반드시 KIS 공식 문서
#    (https://apiportal.koreainvestment.com) 최신본과 대조 확인할 것을 권장한다.
KIS_TR_ID = {
    # 국내업종 현재지수 (코스피/코스닥)
    "index_price": "FHPUP02100000",
    "index_price_path": "/uapi/domestic-stock/v1/quotations/inquire-index-price",

    # 주식현재가 시세 (PER/PBR 포함)
    "stock_price": "FHKST01010100",
    "stock_price_path": "/uapi/domestic-stock/v1/quotations/inquire-price",

    # 국내업종 일자별지수 (200일 이동평균 계산용) — ⚠️ 재확인 권장
    "index_daily_price": "FHPUP02120000",
    "index_daily_price_path": "/uapi/domestic-stock/v1/quotations/inquire-index-daily-price",

    # 주식현재가 일자별 (RSI 계산용) — ⚠️ 재확인 권장
    "stock_daily_price": "FHKST01010400",
    "stock_daily_price_path": "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
}

# KIS 업종 코드
KIS_INDEX_CODES = {
    "KOSPI": "0001",
    "KOSDAQ": "1001",
}

MA_WINDOW = 200   # 시장 국면 판단용 이동평균 기간

# ------------------------------------------------------------------
# 8대 섹터 대표주 유니버스  {섹터명: [(종목명, 종목코드), ...]}
# ------------------------------------------------------------------
SECTOR_STOCKS = {
    "반도체/IT": [("삼성전자", "005930"), ("SK하이닉스", "000660")],
    "이차전지/배터리": [("LG에너지솔루션", "373220"), ("POSCO홀딩스", "005490")],
    "바이오/제약": [("삼성바이오로직스", "207940"), ("셀트리온", "068270")],
    "자동차/운송": [("현대차", "005380"), ("기아", "000270")],
    "금융/지주": [("KB금융", "105560"), ("신한지주", "055550")],
    "플랫폼/소프트웨어": [("NAVER", "035420"), ("카카오", "035720")],
    "방산/조선": [("한화에어로스페이스", "012450"), ("HD현대중공업", "329180")],
    "전력/인프라": [("한국전력", "015760"), ("LS일렉트릭", "010120")],
}

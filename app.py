"""
Mini Quant Dashboard - 메인 엔트리포인트

실행:
    streamlit run app.py
"""

import streamlit as st

import db
import utils.holiday as holiday
import utils.kis_api as kis_api
import utils.market_hours as market_hours
import utils.risk as risk
import utils.telegram_bot as telegram_bot
from config import AUTOREFRESH_INTERVAL_SEC, KILL_SWITCH_THRESHOLD
from db import init_db
from pages_impl import detail, market_overview, portfolio_analysis

st.set_page_config(
    page_title="Mini Quant Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------
# 자동 새로고침: 장 운영시간(KST, 월~금 09:00~16:00)에만 15초 주기로 동작한다.
# streamlit-autorefresh를 우선 사용하고, 미설치 환경에서도 앱이 죽지 않도록
# HTML meta-refresh로 폴백한다. 장 마감/주말에는 아예 새로고침을 걸지 않는다.
# (KIS 시세 캐시 TTL과 동일한 주기로 맞춰, 새로고침될 때마다 최신 시세를 당겨오도록 함)
# --------------------------------------------------------------
def _enable_autorefresh(interval_sec: int) -> None:
    try:
        from streamlit_autorefresh import st_autorefresh

        st_autorefresh(interval=interval_sec * 1000, key="kis_dashboard_autorefresh")
    except ImportError:
        # streamlit-autorefresh 미설치 시: 브라우저 meta 태그로 전체 페이지를 주기적으로 새로고침한다.
        st.markdown(
            f'<meta http-equiv="refresh" content="{interval_sec}">',
            unsafe_allow_html=True,
        )


_weekday_hours_ok = market_hours.is_market_open()  # 요일 + 시간 조건만 (휴장일 캘린더 미반영)

# 휴장일 캘린더는 요일/시간이 이미 장중일 때만 확인한다 (불필요한 API 호출 절약).
# 조회 불가(None)일 때는 fail-open으로 처리해 요일/시간 판단 결과를 그대로 따른다.
_is_holiday: bool | None = holiday.is_holiday(market_hours.now_kst()) if _weekday_hours_ok else None
_market_open = _weekday_hours_ok and not _is_holiday

if _market_open:
    _enable_autorefresh(AUTOREFRESH_INTERVAL_SEC)

# --------------------------------------------------------------
# 다크/라이트 모드 모두에서 자연스럽게 보이도록 Streamlit 테마 변수 활용
# --------------------------------------------------------------
st.markdown(
    """
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 3rem; }

        div[data-testid="stMetric"] {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 12px;
            padding: 14px 16px;
        }

        .badge {
            display: inline-block;
            padding: 8px 18px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 1.05rem;
            margin-top: 6px;
        }
        .badge-green {
            background-color: rgba(34,197,94,0.15);
            color: #16a34a;
            border: 1px solid rgba(34,197,94,0.4);
        }
        .badge-red {
            background-color: rgba(239,68,68,0.15);
            color: #dc2626;
            border: 1px solid rgba(239,68,68,0.4);
        }

        .kill-switch-banner {
            background: linear-gradient(90deg, #dc2626, #991b1b);
            color: white;
            padding: 18px 22px;
            border-radius: 14px;
            font-size: 1.3rem;
            font-weight: 800;
            text-align: center;
            margin-bottom: 20px;
            box-shadow: 0 4px 18px rgba(220,38,38,0.35);
        }

        .sector-card {
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 8px;
            background-color: var(--secondary-background-color);
        }

        .source-tag {
            font-size: 0.78rem;
            opacity: 0.65;
            margin-top: 4px;
        }

        .config-warning-card {
            border: 1px solid rgba(234,179,8,0.5);
            background-color: rgba(234,179,8,0.10);
            border-radius: 14px;
            padding: 20px 24px;
            font-size: 1.05rem;
            line-height: 1.7;
        }

        .market-status-badge {
            display: inline-block;
            width: 100%;
            box-sizing: border-box;
            padding: 8px 14px;
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.92rem;
            text-align: center;
            margin-bottom: 6px;
        }
        .market-status-open {
            background-color: rgba(239,68,68,0.12);
            color: #dc2626;
            border: 1px solid rgba(239,68,68,0.35);
        }
        .market-status-closed {
            background-color: rgba(34,197,94,0.12);
            color: #16a34a;
            border: 1px solid rgba(34,197,94,0.35);
        }

        .recommend-card {
            border: 1px solid rgba(34,197,94,0.5);
            background-color: rgba(34,197,94,0.08);
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 10px;
        }

        .signal-badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            border: 1px solid;
            margin-right: 6px;
            margin-bottom: 4px;
        }

        .factor-row {
            display: flex;
            flex-wrap: wrap;
            gap: 14px;
            font-size: 0.9rem;
            opacity: 0.9;
        }

        /* 카드형 레이아웃(st.container(border=True)) 간 세로 여백을 정리 */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            margin-bottom: 10px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# 앱 시작 시 SQLite 테이블 초기화 (최초 1회는 자동으로 초기 자금 세팅)
init_db()

st.sidebar.title("📊 Mini Quant Dashboard")

# --------------------------------------------------------------
# 장 운영시간(KST) 상태 라벨
# 장중: 🔴 장중 실시간 동기화 중 (15초 주기)  /  장마감·주말: 🟢 장마감 (정적 시세 유지 중)
# --------------------------------------------------------------
if _market_open:
    st.sidebar.markdown(
        '<div class="market-status-badge market-status-open">🔴 장중 실시간 동기화 중 (15초 주기)</div>',
        unsafe_allow_html=True,
    )
elif _weekday_hours_ok and _is_holiday:
    # 요일/시간상으로는 장중이지만, 한국거래소 휴장일 캘린더 조회 결과 휴장일로 확인된 경우
    st.sidebar.markdown(
        '<div class="market-status-badge market-status-closed">🟢 장마감 (한국거래소 휴장일)</div>',
        unsafe_allow_html=True,
    )
else:
    st.sidebar.markdown(
        '<div class="market-status-badge market-status-closed">🟢 장마감 (정적 시세 유지 중)</div>',
        unsafe_allow_html=True,
    )
st.sidebar.caption(f"기준 시각(KST): {market_hours.now_kst().strftime('%Y-%m-%d (%a) %H:%M:%S')}")

page = st.sidebar.radio(
    "메뉴",
    ["📈 지수 및 시장 현황", "💼 포트폴리오 & 퀀트 분석", "Detail"],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
if _market_open:
    st.sidebar.caption(
        f"시세는 한국투자증권(KIS) Open API 실시간 데이터를 사용하며, {AUTOREFRESH_INTERVAL_SEC}초마다 "
        "자동으로 새로고침되어 최신 시세를 반영합니다 (캐시 TTL도 동일하게 적용).\n\n"
        "본 대시보드는 학습/시뮬레이션 목적의 페이퍼 트레이딩이며 실제 매매를 지원하지 않습니다."
    )
elif _weekday_hours_ok and _is_holiday:
    st.sidebar.caption(
        "한국거래소 휴장일 캘린더 조회 결과 오늘은 휴장일입니다. 자동 새로고침이 중지되고, "
        "직전에 조회된 정적 시세가 유지됩니다.\n\n"
        "본 대시보드는 학습/시뮬레이션 목적의 페이퍼 트레이딩이며 실제 매매를 지원하지 않습니다."
    )
else:
    st.sidebar.caption(
        "현재는 정규장 운영시간(평일 09:00~16:00 KST)이 아니므로 자동 새로고침이 중지되고, "
        "직전에 조회된 정적 시세가 유지됩니다.\n\n"
        "본 대시보드는 학습/시뮬레이션 목적의 페이퍼 트레이딩이며 실제 매매를 지원하지 않습니다."
    )

# --------------------------------------------------------------
# KIS API 키 미설정 시: 앱이 죽지 않고 안내 카드만 표시 (Detail 페이지는 API 없이도 열람 가능)
# --------------------------------------------------------------
if page == "Detail":
    detail.render()
elif not kis_api.is_configured():
    st.title("Mini Quant Dashboard")
    error_message = kis_api.get_config_error_message() or (
        "⚠️ .streamlit/secrets.toml 파일에 한국투자증권 API Key를 설정해주세요."
    )
    st.markdown(
        f"""
        <div class="config-warning-card">
        {error_message}<br><br>
        <b>설정 방법</b><br>
        프로젝트 루트에 <code>.streamlit/secrets.toml</code> 파일을 만들고 아래와 같이 입력하세요.
        <pre style="margin-top:10px;">
[kis]
APP_KEY = "발급받은 APP KEY"
APP_SECRET = "발급받은 APP SECRET"
CANO = "계좌번호 앞 8자리"
ACNT_PRDT_CD = "계좌상품코드 (보통 01)"
IS_VIRTUAL = true   # 모의투자면 true, 실전투자면 false
        </pre>
        API Key는 <a href="https://apiportal.koreainvestment.com" target="_blank">한국투자증권 Open API 포털</a>에서 발급받을 수 있습니다.
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    # --------------------------------------------------------------
    # 계좌 전체 킬 스위치: 어느 페이지에 있든 대시보드 최상단에 경고 배너를 표시한다.
    # (보유 종목 평가금액은 utils.risk가 KIS 실시간 시세로 계산하며, 15초 캐시를 공유한다)
    # 새로 발동되는 순간(엣지 트리거)에만 텔레그램 알림을 1회 발송하고,
    # 해제되면 플래그를 초기화해 다음 재발동 시 다시 알림이 가도록 한다.
    # --------------------------------------------------------------
    account_status = risk.compute_account_status()
    if account_status["is_kill_switch_active"]:
        already_notified = db.get_app_state("kill_switch_notified", "0") == "1"
        if not already_notified and telegram_bot.is_configured():
            message = (
                "[🚨 Mini Quant 계좌 킬 스위치 발동]\n"
                f"계좌 손실률 {account_status['total_return_pct']:.2f}% "
                f"({KILL_SWITCH_THRESHOLD*100:.0f}% 기준 도달) — 신규 매수가 잠겼습니다."
            )
            ok, _ = telegram_bot.send_message(message)
            if ok:
                db.set_app_state("kill_switch_notified", "1")

        st.markdown(
            f"""<div class='kill-switch-banner'>
            🚨 계좌 리스크 킬 스위치 작동 ({KILL_SWITCH_THRESHOLD*100:.0f}% 손실 도달): 신규 매수 강제 잠금<br>
            <span style='font-size:0.95rem; font-weight:500;'>
            현재 계좌 손실률 {account_status['total_return_pct']:.2f}% —
            모든 종목의 신규 가상 매수가 잠겨 있습니다. 전략을 재점검한 뒤 계속하세요.
            </span></div>""",
            unsafe_allow_html=True,
        )
    else:
        db.set_app_state("kill_switch_notified", "0")

    if page == "📈 지수 및 시장 현황":
        market_overview.render()
    else:
        portfolio_analysis.render()

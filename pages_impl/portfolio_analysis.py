"""페이지 2: 포트폴리오 현황 및 분석 (Portfolio & Quant Analysis) — KIS Open API 실시간 시세 기반"""

import pandas as pd
import streamlit as st

import db
import utils.strategy_engine as strategy_engine
import utils.telegram_bot as telegram_bot
from config import (
    DEFAULT_STOP_LOSS_LEVELS,
    INITIAL_CAPITAL,
    KILL_SWITCH_THRESHOLD,
    SECTOR_STOCKS,
)
from utils.data_fetcher import get_index_snapshot, get_stock_rsi, get_stock_snapshot


TELEGRAM_TEST_MESSAGE = "📱 [Mini Quant] 대시보드 알림 연동 테스트 성공!"


def _telegram_test_button(key: str) -> None:
    """
    기존 Mock 버튼을 대체하는 실제 텔레그램 연동 테스트 버튼.
    클릭 시 고정된 테스트 메시지를 실제로 전송해 연동 여부를 확인할 수 있다.
    응답 지연(ReadTimeout)으로 확인만 안 된 경우는 실패(빨간 에러)로 표시하지 않고
    별도의 경고 문구로 구분해서 보여준다.
    """
    if st.button("텔레그램 알림 전송", key=key):
        ok, msg = telegram_bot.send_message(TELEGRAM_TEST_MESSAGE)
        if ok and msg == telegram_bot.SUCCESS_MESSAGE:
            st.success("실제 텔레그램으로 테스트 메시지를 보냈습니다.")
        elif ok:
            # 응답 확인이 지연된 경우(ReadTimeout 등) — 실패로 단정하지 않고 안내만 표시
            st.warning(msg)
        else:
            st.error(f"텔레그램 전송에 실패했습니다: {msg}")


# ------------------------------------------------------------------
# 공통 유틸
# ------------------------------------------------------------------
def _all_universe():
    """[(섹터, 종목명, 종목코드), ...] 전체 유니버스 리스트"""
    universe = []
    for sector, stocks in SECTOR_STOCKS.items():
        for name, code in stocks:
            universe.append((sector, name, code))
    return universe


# ------------------------------------------------------------------
# 1) 퀀트 시그널 스크리너 + 매수 추천 시그널 (전략 엔진)
# ------------------------------------------------------------------
def _notify_buy_signal(name: str, code: str, price_snap: dict, rsi: float) -> None:
    """
    매수 추천 시그널이 처음 포착된 종목에 한해(같은 날 중복 발송 방지) 텔레그램으로 알린다.
    텔레그램이 설정되어 있지 않으면 조용히 건너뛴다.
    """
    if not telegram_bot.is_configured():
        return
    if db.has_notified_today("buy_signal", code):
        return

    message = (
        "[🟢 Mini Quant 매수 추천 시그널]\n"
        f"- 종목: {name}({code})\n"
        f"- 현재가: {price_snap['price']:,.0f}원 (등락률 {price_snap['change_pct']:+.1f}%)\n"
        f"- 포착 사유: KOSPI 상승국면 + RSI({rsi:.1f}) 과매도 + 저PBR/PER 구간 진입"
    )
    ok, _ = telegram_bot.send_message(message)
    if ok:
        db.mark_notified("buy_signal", code)


def _build_screener() -> tuple[pd.DataFrame, list[str], bool]:
    """스크리너 결과 DataFrame, 조회 실패한 종목명 목록, 매크로(코스피) 공격모드 여부를 반환한다."""
    kospi_snap = get_index_snapshot("KOSPI")
    macro_ok = strategy_engine.is_macro_bullish(kospi_snap.get("regime"))

    rows = []
    failed = []

    for sector, name, code in _all_universe():
        price_snap = get_stock_snapshot(code, name)
        if not price_snap["available"]:
            failed.append(name)
            continue

        rsi_snap = get_stock_rsi(code)
        rsi = rsi_snap["rsi"] if rsi_snap["available"] else None
        per = price_snap.get("per")
        pbr = price_snap.get("pbr")

        quant_ok, quant_reasons = strategy_engine.evaluate_quant_conditions(rsi, pbr, per)
        recommend = macro_ok and quant_ok

        signals = []
        if rsi is not None and rsi <= strategy_engine.RSI_OVERSOLD_THRESHOLD:
            signals.append("RSI 과매도")
        if pbr is not None and pbr < strategy_engine.PBR_UNDERVALUED_THRESHOLD:
            signals.append("저PBR")
        if per is not None and 0 < per <= strategy_engine.PER_UNDERVALUED_MAX:
            signals.append("저PER")

        if signals:
            reasons = (["코스피 200일선 위 (공격 모드)"] if macro_ok else []) + quant_reasons
            rows.append(
                {
                    "섹터": sector,
                    "종목명": name,
                    "종목코드": code,
                    "현재가": round(price_snap["price"], 0),
                    "시그널": " / ".join(signals),
                    "PER": per,
                    "PBR": pbr,
                    "RSI": round(rsi, 1) if rsi is not None else None,
                    "실시간여부": price_snap["is_live"],
                    "매수추천": recommend,
                    "추천사유": reasons,
                }
            )
            if recommend and rsi is not None:
                _notify_buy_signal(name, code, price_snap, rsi)

    return pd.DataFrame(rows), failed, macro_ok


def _render_recommend_card(row) -> None:
    reasons_html = "<br>".join(f"· {r}" for r in row["추천사유"])
    st.markdown(
        f"""<div class='recommend-card'>
        <b>가상 매수 추천 시그널 — {row['종목명']} ({row['종목코드']})</b><br>
        현재가 {row['현재가']:,.0f}원<br>
        <span class='source-tag'>{reasons_html}</span>
        </div>""",
        unsafe_allow_html=True,
    )
    _telegram_test_button(key=f"tg_reco_{row['종목코드']}")


def _signal_badges_html(signals_str: str) -> str:
    """시그널 문자열("RSI 과매도 / 저PBR")을 색상이 구분된 배지(태그)로 변환한다."""
    badge_style = {
        "RSI 과매도": "#dc2626",
        "저PBR": "#2563eb",
        "저PER": "#7c3aed",
    }
    spans = []
    for label in [s.strip() for s in signals_str.split("/") if s.strip()]:
        color = badge_style.get(label, "#6b7280")
        spans.append(
            f"<span class='signal-badge' "
            f"style='color:{color}; border-color:{color}55; background-color:{color}18;'>"
            f"{label}</span>"
        )
    return "".join(spans)


def _render_watchlist_cards(df: pd.DataFrame) -> None:
    """
    조건 부분 충족 종목을 모바일에서도 가독성이 좋은 카드형 레이아웃으로 렌더링한다.
    카드 1행: 종목명(코드) / 현재가 / 시그널 배지
    카드 2행: PER · PBR · RSI 컴팩트 표시
    카드 3행: 텔레그램 알림 전송 버튼
    """
    for _, row in df.iterrows():
        with st.container(border=True):
            live_mark = "" if row["실시간여부"] else " ⚠️"
            recommend_mark = " 🟢" if row["매수추천"] else ""

            top_left, top_right = st.columns([2.4, 1.2])
            with top_left:
                st.markdown(
                    f"**{row['종목명']}{recommend_mark}{live_mark}**  \n"
                    f"<span class='source-tag'>{row['종목코드']} · {row['섹터']}</span>",
                    unsafe_allow_html=True,
                )
            with top_right:
                st.markdown(
                    f"<div style='text-align:right; font-size:1.1rem; font-weight:700; "
                    f"margin-top:2px;'>{row['현재가']:,.0f}원</div>",
                    unsafe_allow_html=True,
                )

            st.markdown(
                f"<div style='margin:6px 0 8px 0;'>{_signal_badges_html(row['시그널'])}</div>",
                unsafe_allow_html=True,
            )

            per_text = f"{row['PER']:.1f}" if row["PER"] is not None else "-"
            pbr_text = f"{row['PBR']:.2f}" if row["PBR"] is not None else "-"
            rsi_text = f"{row['RSI']:.1f}" if row["RSI"] is not None else "-"
            st.markdown(
                f"<div class='factor-row'>"
                f"<span><b>PER</b> {per_text}</span>"
                f"<span><b>PBR</b> {pbr_text}</span>"
                f"<span><b>RSI</b> {rsi_text}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
            _telegram_test_button(key=f"tg_{row['종목코드']}")


def _render_screener():
    st.subheader("퀀트 시그널 스크리너 (Strategy Screener)")
    st.caption("샘플 조건 · RSI ≤ 30(과매도) / PBR < 1.0(저PBR) / PER ≤ 10(저PER) · KIS 실시간 시세 기반")

    with st.spinner("KIS API로 전 종목 팩터를 순차 조회하는 중... (Rate Limit 방지를 위해 지연 적용)"):
        df, failed, macro_ok = _build_screener()

    if failed:
        st.warning(f"다음 종목은 시세 조회에 실패해 스크리너에서 제외되었습니다: {', '.join(failed)}")

    if df.empty:
        st.info("현재 조건을 만족하는 종목이 없습니다.")
        return

    recommended_df = df[df["매수추천"]]

    if not recommended_df.empty:
        st.markdown("#### 가상 매수 추천 시그널")
        st.caption("코스피 200일선 위(공격 모드) + RSI/PBR/PER 조건을 모두 만족한 종목입니다.")
        for _, row in recommended_df.iterrows():
            _render_recommend_card(row)
        st.markdown("---")
    elif not macro_ok:
        st.caption("코스피가 200일 이동평균선 아래(방어 모드)라 매수 추천 시그널이 발생하지 않습니다.")

    st.markdown("#### 조건 부분 충족 종목 (관심 목록)")
    _render_watchlist_cards(df)


# ------------------------------------------------------------------
# 2) 페이퍼 트레이딩 & 리스크 모니터
# ------------------------------------------------------------------
def _account_summary(positions: list[dict]):
    cash = db.get_cash()
    market_value = 0.0
    enriched = []
    any_stale = False

    for pos in positions:
        snap = get_stock_snapshot(pos["code"], pos["name"])
        if snap["available"]:
            current_price = snap["price"]
            if not snap["is_live"]:
                any_stale = True
        else:
            # 현재가 조회 완전 실패 + 과거 성공 데이터도 없는 경우에만 진입가로 임시 표시
            current_price = pos["entry_price"]
            any_stale = True

        value = current_price * pos["quantity"]
        market_value += value
        pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
        enriched.append(
            {
                **pos,
                "current_price": current_price,
                "pnl_pct": pnl_pct,
                "value": value,
                "is_live": snap.get("is_live", False),
            }
        )

    total_equity = cash + market_value
    total_return_pct = (total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    return cash, market_value, total_equity, total_return_pct, enriched, any_stale


def _apply_auto_stop_loss(enriched: list[dict]) -> list[str]:
    """
    보유 종목의 수익률이 설정된 손절 기준에 도달(이하)하면 자동으로 가상 매도 처리하고,
    매도된 종목 설명 문자열 목록을 반환한다. (DB에 매도 이력이 함께 기록되고,
    텔레그램이 설정되어 있으면 손절 매도 알림도 함께 발송된다)
    """
    triggered = []
    for pos in enriched:
        threshold_pct = pos["stop_loss_pct"] * 100  # 예: -0.03 -> -3.0
        if pos["pnl_pct"] <= threshold_pct:
            ok, _ = db.sell_position(pos["id"], pos["current_price"])
            if ok:
                triggered.append(f"{pos['name']} ({pos['pnl_pct']:.2f}%, 기준 {threshold_pct:.0f}%)")
                if telegram_bot.is_configured():
                    message = (
                        f"[⚠️ 손절 매도 알림] {pos['name']}"
                        f"({pos['pnl_pct']:.1f}% 도달) 가상 매도 완료 및 현금화."
                    )
                    telegram_bot.send_message(message)
    return triggered


def _stop_loss_progress(pnl_pct: float, stop_loss_pct: float) -> tuple[float, str]:
    """
    현재 수익률이 손절 기준에 얼마나 근접했는지 0.0~1.0 비율과 상태 라벨을 반환한다.
    수익 구간(pnl_pct >= 0)이면 항상 안전(0.0)으로 처리한다.
    """
    threshold_pct = stop_loss_pct * 100
    if pnl_pct >= 0 or threshold_pct == 0:
        return 0.0, "안전"

    ratio = min(abs(pnl_pct) / abs(threshold_pct), 1.0)
    ratio = round(ratio, 6)  # 부동소수점 오차로 경계값(0.8/0.5)에서 라벨이 어긋나지 않도록 보정

    if ratio >= 0.8:
        label = "위험"
    elif ratio >= 0.5:
        label = "주의"
    else:
        label = "안전"
    return ratio, label


def _render_buy_form(kill_switch_active: bool):
    st.markdown("#### 가상 매수")
    universe = _all_universe()
    labels = [f"{name} ({code}) · {sector}" for sector, name, code in universe]

    with st.form("buy_form"):
        bc1, bc2, bc3 = st.columns([3, 1, 1])
        choice = bc1.selectbox("종목 선택", labels)
        qty = bc2.number_input("수량", min_value=1, value=1, step=1)
        stop_loss = bc3.selectbox(
            "목표 손절가", DEFAULT_STOP_LOSS_LEVELS, format_func=lambda x: f"{x*100:.0f}%"
        )
        submitted = st.form_submit_button("가상 매수 실행", disabled=kill_switch_active)

    if kill_switch_active:
        st.caption("킬 스위치 활성화 상태에서는 신규 매수가 잠겨 있습니다.")

    if submitted and not kill_switch_active:
        idx = labels.index(choice)
        sector, name, code = universe[idx]
        snap = get_stock_snapshot(code, name)
        if not snap["available"]:
            st.error(f"현재가를 불러오지 못해 매수를 진행할 수 없습니다. ({snap.get('warning', '')})")
            return
        if not snap["is_live"]:
            st.warning("최근 성공 시세(지연 데이터)로 체결됩니다. 실시간 시세가 아닐 수 있습니다.")

        price = snap["price"]
        ok, msg = db.buy_stock(code, name, price, int(qty), float(stop_loss))
        if ok:
            st.success(f"{name} {qty}주 매수 완료 (체결가 {price:,.0f}원)")
            st.cache_data.clear()
            st.rerun()
        else:
            st.warning(msg)


def _render_holdings(enriched: list[dict]):
    st.markdown("#### 가상 보유 종목")
    if not enriched:
        st.info("보유 중인 종목이 없습니다.")
        return

    header_cols = st.columns([1.8, 1.3, 1.3, 1.3, 2.2, 1])
    for col, label in zip(
        header_cols, ["종목명", "진입가", "현재가", "수익률", "목표 손절가", "매도"]
    ):
        col.markdown(f"**{label}**")

    progress_color = {"안전": "🟢", "주의": "🟡", "위험": "🔴"}

    for pos in enriched:
        targets = {
            f"{lvl*100:.0f}%": pos["entry_price"] * (1 + lvl) for lvl in DEFAULT_STOP_LOSS_LEVELS
        }
        c1, c2, c3, c4, c5, c6 = st.columns([1.8, 1.3, 1.3, 1.3, 2.2, 1])
        stale_mark = "" if pos.get("is_live") else " ⚠️"
        c1.markdown(f"**{pos['name']}{stale_mark}**  \n`{pos['code']}`")
        c2.write(f"{pos['entry_price']:,.0f}")
        c3.write(f"{pos['current_price']:,.0f}")

        pnl_color = "#16a34a" if pos["pnl_pct"] >= 0 else "#dc2626"
        c4.markdown(
            f"<span style='color:{pnl_color}; font-weight:700;'>{pos['pnl_pct']:+.2f}%</span>",
            unsafe_allow_html=True,
        )
        c5.write(" / ".join([f"{k}: {v:,.0f}원" for k, v in targets.items()]))

        if c6.button("매도", key=f"sell_{pos['id']}"):
            ok, msg = db.sell_position(pos["id"], pos["current_price"])
            if ok:
                st.success(msg)
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning(msg)

        ratio, label = _stop_loss_progress(pos["pnl_pct"], pos["stop_loss_pct"])
        st.progress(
            ratio,
            text=f"{progress_color[label]} 손절가까지 {ratio*100:.0f}% 근접 ({label})",
        )
        st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)


def _render_paper_trading():
    st.subheader("페이퍼 트레이딩 & 리스크 모니터")

    positions = db.get_positions()
    with st.spinner("KIS API로 보유 종목 현재가를 조회하는 중..."):
        cash, market_value, total_equity, total_return_pct, enriched, any_stale = _account_summary(
            positions
        )

    # ------------------------------------------------------------------
    # 자동 손절 실행: 손절 기준에 도달한 포지션을 즉시 가상 매도 처리한다.
    # (매도 후에는 화면을 새로고침해 최신 보유 목록/잔고를 반영한다)
    # ------------------------------------------------------------------
    auto_sold = _apply_auto_stop_loss(enriched)
    if auto_sold:
        st.session_state["_auto_stop_loss_notice"] = auto_sold
        st.cache_data.clear()
        st.rerun()

    notice = st.session_state.pop("_auto_stop_loss_notice", None)
    if notice:
        st.warning("손절가 도달 — 다음 종목이 자동으로 매도되었습니다: " + ", ".join(notice))

    kill_switch_active = total_return_pct <= KILL_SWITCH_THRESHOLD * 100
    # 계좌 전체 킬 스위치 경고 배너는 app.py에서 모든 페이지 최상단에 공통으로 표시한다.

    if any_stale:
        st.caption("KIS 일시 응답 지연 (최근 성공 시세 유지 중) — 일부 보유 종목의 현재가가 지연 데이터일 수 있습니다.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("초기 자금", f"{INITIAL_CAPITAL:,.0f}원")
    m2.metric("현금 잔고", f"{cash:,.0f}원")
    m3.metric("평가 자산 합계", f"{total_equity:,.0f}원", delta=f"{total_return_pct:+.2f}%")
    m4.metric("보유 종목 수", f"{len(positions)}개")

    st.markdown("---")
    _render_buy_form(kill_switch_active)

    st.markdown("---")
    _render_holdings(enriched)

    with st.expander("거래 내역 보기"):
        trades = db.get_trades()
        if trades:
            trades_df = pd.DataFrame(trades)[
                ["timestamp", "action", "name", "code", "price", "quantity"]
            ]
            trades_df.columns = ["시각", "구분", "종목명", "종목코드", "체결가", "수량"]
            st.dataframe(trades_df, use_container_width=True, hide_index=True)
        else:
            st.caption("거래 내역이 없습니다.")

    st.markdown("")
    if st.button("가상계좌 초기화"):
        db.reset_account()
        st.cache_data.clear()
        st.rerun()


def render():
    st.title("Portfolio & Quant Analysis")

    _render_screener()
    st.markdown("---")
    _render_paper_trading()

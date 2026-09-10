"""페이지 1: 지수 및 시장 현황 (Market Overview) — 지수/종목: 한국투자증권 KIS API, 환율: 네이버 금융"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from config import ASSET_CLASS_ETFS, SECTOR_STOCKS
from utils.data_fetcher import get_fx_snapshot, get_index_snapshot, get_stock_snapshot

SOURCE_LABEL_KIS = "한국투자증권 REST API"
SOURCE_LABEL_NAVER = "네이버 금융"


def _regime_badge_html(regime: Optional[str]) -> str:
    if regime == "공격":
        return '<span class="badge badge-green">🟢 공격 모드 (안정)</span>'
    if regime == "방어":
        return '<span class="badge badge-red">🔴 방어 모드 (위험)</span>'
    return '<span class="badge" style="background-color:rgba(148,163,184,0.15); color:#64748b; border:1px solid rgba(148,163,184,0.4);">⏳ 국면 판정 보류 (히스토리 조회 실패)</span>'


def _sync_caption(synced_at, is_live: bool, warning: Optional[str], source_label: str) -> str:
    """출처 및 동기화 시각 표기 (예: 🏷️ 출처: 한국투자증권 REST API | 동기화: 14:25:30)"""
    time_str = synced_at.strftime("%H:%M:%S") if synced_at else "-"
    base = f"🏷️ 출처: {source_label} | 동기화: {time_str}"
    if not is_live and warning:
        return f"{warning}<br><span class='source-tag'>{base}</span>"
    return f"<span class='source-tag'>{base}</span>"


def _render_regime_section():
    st.subheader("🚦 시장 국면 신호등 (Market Regime Guardrail)")
    cols = st.columns(3)

    with st.spinner("KIS API로 지수/환율 시세를 조회하는 중..."):
        kospi = get_index_snapshot("KOSPI")
        kosdaq = get_index_snapshot("KOSDAQ")
        fx = get_fx_snapshot()

    for col, snap in zip(cols[:2], [kospi, kosdaq]):
        with col:
            label = snap["name"]
            if not snap["available"]:
                st.error(f"{label} 시세를 불러오지 못했습니다.\n\n{snap.get('warning', '')}")
                continue

            st.metric(
                label=f"{label} 지수",
                value=f"{snap['current']:,.2f}",
                delta=f"{snap['change_pct']:+.2f}%",
            )
            st.markdown(_regime_badge_html(snap["regime"]), unsafe_allow_html=True)
            if snap["ma200"] is not None:
                st.caption(f"200일 이동평균: {snap['ma200']:,.2f}")
            st.markdown(
                _sync_caption(snap["synced_at"], snap["is_live"], snap["warning"], SOURCE_LABEL_KIS),
                unsafe_allow_html=True,
            )

    with cols[2]:
        if not fx["available"]:
            st.error(f"환율 시세를 불러오지 못했습니다.\n\n{fx.get('warning', '')}")
        else:
            st.metric(
                label="원/달러 환율 (USD/KRW)",
                value=f"{fx['price']:,.2f}",
                delta=f"{fx['change_pct']:+.2f}%",
            )
            st.markdown(
                _sync_caption(fx["synced_at"], fx["is_live"], fx["warning"], SOURCE_LABEL_NAVER),
                unsafe_allow_html=True,
            )


def _render_stock_card_html(stock_name: str, snap: dict) -> None:
    """섹터/자산군 공용 종목 카드 렌더러 (모바일 카드형 레이아웃 유지)."""
    if not snap["available"]:
        st.markdown(
            f"<div class='sector-card'>❗ {stock_name} 데이터 조회 실패<br>"
            f"<span class='source-tag'>{snap.get('warning', '')}</span></div>",
            unsafe_allow_html=True,
        )
        return

    arrow = "🔺" if snap["change_pct"] >= 0 else "🔻"
    color = "#16a34a" if snap["change_pct"] >= 0 else "#dc2626"
    warn_line = f"<br>{snap['warning']}" if not snap["is_live"] and snap["warning"] else ""
    time_str = snap["synced_at"].strftime("%H:%M:%S") if snap["synced_at"] else "-"

    st.markdown(
        f"""<div class='sector-card'>
        <b>{snap['name']}</b> ({snap['code']}){warn_line}<br>
        {snap['price']:,.0f}원 &nbsp;
        <span style='color:{color}; font-weight:600;'>{arrow} {snap['change_pct']:+.2f}%</span><br>
        <span class='source-tag'>🏷️ 출처: {SOURCE_LABEL_KIS} | 동기화: {time_str}</span>
        </div>""",
        unsafe_allow_html=True,
    )


def _render_sector_section():
    st.subheader("🏭 8대 주요 섹터 대표주 현황")

    sector_names = list(SECTOR_STOCKS.keys())
    grid_cols = st.columns(2)

    with st.spinner("KIS API로 섹터별 종목 시세를 조회하는 중... (Rate Limit 방지를 위해 순차 호출)"):
        for i, sector in enumerate(sector_names):
            target_col = grid_cols[i % 2]
            with target_col:
                st.markdown(f"**{sector}**")
                for stock_name, code in SECTOR_STOCKS[sector]:
                    snap = get_stock_snapshot(code, stock_name)
                    _render_stock_card_html(stock_name, snap)


def _render_asset_class_section():
    st.subheader("올웨더 포트폴리오 자산군")
    st.caption(
        "레이 달리오의 올웨더(All-Weather) 포트폴리오 개념을 참고한 자산군별 대표 ETF 시세입니다. "
        "주식만이 아니라 채권·원자재·현금성 자산까지 함께 살펴 분산 정도를 점검해보세요."
    )

    category_names = list(ASSET_CLASS_ETFS.keys())
    tab_labels = ["전체"] + category_names
    tabs = st.tabs(tab_labels)

    with st.spinner("KIS API로 자산군별 ETF 시세를 조회하는 중..."):
        # 카테고리별로 한 번만 조회하고(캐시 적용) 탭마다 재사용한다.
        snapshots_by_category: dict[str, list[tuple[str, dict]]] = {}
        for category, etfs in ASSET_CLASS_ETFS.items():
            snapshots_by_category[category] = [
                (name, get_stock_snapshot(code, name)) for name, code in etfs
            ]

    for tab, label in zip(tabs, tab_labels):
        with tab:
            if label == "전체":
                categories_to_show = category_names
            else:
                categories_to_show = [label]

            for category in categories_to_show:
                if label == "전체":
                    st.markdown(f"**{category}**")
                # 카테고리마다 컬럼을 새로 만든다 — 헤더(st.markdown)와 카드가 서로 다른
                # 컬럼 컨텍스트에 걸쳐 있으면 Streamlit이 순서를 보장하지 못해, 헤더들이
                # 카드 그리드 전체 아래로 밀려버리는 렌더링 순서 버그가 있었다.
                grid_cols = st.columns(2)
                for i, (stock_name, snap) in enumerate(snapshots_by_category[category]):
                    with grid_cols[i % 2]:
                        _render_stock_card_html(stock_name, snap)


def render():
    st.title("Market Overview")
    st.caption("시장 국면 신호등 · 8대 섹터 대표주 현황 · 올웨더 자산군 · 한국투자증권 Open API 실시간 시세")

    _render_regime_section()
    st.markdown("---")
    _render_sector_section()
    st.markdown("---")
    _render_asset_class_section()

"""
전략 엔진: 매크로 국면(KOSPI 200일선) + 퀀트 조건(RSI/PBR/PER)을 결합해
가상 매수 추천 시그널을 판단하는 순수 로직 모듈.

외부 API를 직접 호출하지 않고, 이미 조회된 지수/종목 데이터를 인자로 받아
판단만 수행하므로 네트워크 의존성이 없어 단위 테스트가 쉽다.

시그널 조건:
  조건 A (매크로 국면) - KOSPI 지수가 200일 이동평균선 위에 위치 (공격 모드)
  조건 B (퀀트 스크리너) - RSI <= 30 AND PBR < 1.0 AND (0 < PER <= 10)
  조건 A와 B가 동시에 충족될 때만 매수 추천 시그널을 발생시킨다.
"""

from __future__ import annotations

RSI_OVERSOLD_THRESHOLD = 30
PBR_UNDERVALUED_THRESHOLD = 1.0
PER_UNDERVALUED_MAX = 10


def is_macro_bullish(kospi_regime: str | None) -> bool:
    """KOSPI가 200일 이동평균선 위(공격 모드)인지 여부. 국면 판정이 불가능하면 False로 취급한다."""
    return kospi_regime == "공격"


def evaluate_quant_conditions(
    rsi: float | None, pbr: float | None, per: float | None
) -> tuple[bool, list[str]]:
    """
    RSI/PBR/PER 조건을 각각 확인하고, 만족한 조건의 사유 문구 목록을 함께 반환한다.
    세 조건을 모두 만족해야 quant_ok=True 이다 (AND 조건).
    """
    rsi_ok = rsi is not None and rsi <= RSI_OVERSOLD_THRESHOLD
    pbr_ok = pbr is not None and pbr < PBR_UNDERVALUED_THRESHOLD
    per_ok = per is not None and 0 < per <= PER_UNDERVALUED_MAX

    reasons = []
    if rsi_ok:
        reasons.append(f"RSI {rsi:.1f} (과매도 ≤ {RSI_OVERSOLD_THRESHOLD})")
    if pbr_ok:
        reasons.append(f"PBR {pbr:.2f} (저평가 < {PBR_UNDERVALUED_THRESHOLD:.1f})")
    if per_ok:
        reasons.append(f"PER {per:.2f} (저평가 ≤ {PER_UNDERVALUED_MAX})")

    return (rsi_ok and pbr_ok and per_ok), reasons


def evaluate_buy_signal(
    kospi_regime: str | None, rsi: float | None, pbr: float | None, per: float | None
) -> dict:
    """
    조건 A(매크로: KOSPI 공격모드) AND 조건 B(RSI<=30 AND PBR<1.0 AND 0<PER<=10)를
    모두 만족하면 매수 추천 시그널을 발생시킨다.

    반환: {"signal": bool, "macro_ok": bool, "quant_ok": bool, "reasons": list[str]}
    """
    macro_ok = is_macro_bullish(kospi_regime)
    quant_ok, quant_reasons = evaluate_quant_conditions(rsi, pbr, per)
    signal = macro_ok and quant_ok

    reasons = []
    if macro_ok:
        reasons.append("코스피 200일선 위 (공격 모드)")
    reasons.extend(quant_reasons)

    return {"signal": signal, "macro_ok": macro_ok, "quant_ok": quant_ok, "reasons": reasons}

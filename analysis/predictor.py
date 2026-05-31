"""
Surge Score 계산 (v1 + v2 지원)

v1: Volume-heavy (기존)
v2: Supply 35% 중심 + T+1/T+2/T+3 신뢰도 분리 (plan_v2.md)
"""
from typing import List
from utils.models import StockFeatures, AnalysisResult
from utils.helpers import get_next_trading_day
import math

# v2 설정 로드
try:
    from config.settings import get_weights, SUPPLY, MOMENTUM
    _USE_V2_CONFIG = True
except Exception:
    _USE_V2_CONFIG = False


def _clamp(value: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """값을 지정 범위로 클램핑"""
    return max(min_val, min(max_val, value))


def _safe_div(n: float, d: float, default: float = 0.0) -> float:
    if d == 0 or math.isnan(d) or math.isinf(d):
        return default
    return n / d


def compute_surge_score(features: StockFeatures) -> StockFeatures:
    """
    Volume 30% + Momentum 25% + Trend/MA 20% + RSI/MACD 15% + Supply 10%
    고품질 한국어 reason_tags, High/Medium/Low 라벨 + 추천 문구 생성.
    입력 StockFeatures의 기술적/수급 필드를 기반으로 0~100 점수 산출.
    """
    # ----- 1. Volume Score (30%) -----
    vr = _clamp(features.volume_ratio, 0.4, 6.0)
    # 0.8x → ~20점, 1.5x → ~55점, 2.5x → ~80점, 4x+ → 95~100
    vol_score = _clamp((vr - 0.6) / 4.0 * 100.0 + 15)
    if features.volume_explosion:
        vol_score = _clamp(vol_score + 18)
    elif features.volume_spike:
        vol_score = _clamp(vol_score + 10)
    vol_score = _clamp(vol_score, 10, 100)

    # ----- 2. Momentum Score (25%) -----
    # 5일 + 10일 수익률 가중
    mom_raw = (features.five_day_return * 0.65 + features.ten_day_return * 0.35)
    # +12% → 85점대, 0% → 50점, -8% → 30점대
    mom_score = _clamp(50.0 + mom_raw * 3.8)
    mom_score = _clamp(mom_score)

    # ----- 3. Trend/MA Score (20%) -----
    ma_bullish = sum([
        1 if features.above_ma5 else 0,
        1 if features.above_ma20 else 0,
        1 if features.above_ma60 else 0
    ])
    ma_part = (ma_bullish / 3.0) * 65.0
    trend_part = features.trend_strength * 35.0   # -1.0 ~ +1.0
    trend_score = _clamp(ma_part + trend_part + 15)

    # ----- 4. RSI/MACD Oscillator Score (15%) -----
    rsi = _clamp(features.rsi_14, 5, 95)
    if rsi < 28:
        rsi_part = 78   # 과매도 반등 잠재력
    elif rsi < 42:
        rsi_part = 68
    elif rsi < 58:
        rsi_part = 58
    elif rsi < 72:
        rsi_part = 52
    else:
        rsi_part = 38   # 과매수 주의
    # MACD histogram (양수 = 상승 모멘텀)
    macd_h = _clamp(features.macd_hist, -12, 12)
    macd_part = 50.0 + (macd_h * 3.8)
    osc_score = _clamp((rsi_part * 0.6 + macd_part * 0.4))

    # ----- 5. Supply Score (10%) -----
    # netbuy_score + 외국인/기관 실제 금액 반영
    supply_base = _clamp(48.0 + features.netbuy_score * 0.9)
    foreign_boost = 0.0
    if features.foreign_netbuy > 200_000_000:      # 2억 이상
        foreign_boost = 14
    elif features.foreign_netbuy > 50_000_000:
        foreign_boost = 8
    inst_boost = 0.0
    if features.inst_netbuy > 300_000_000:
        inst_boost = 11
    elif features.inst_netbuy > 80_000_000:
        inst_boost = 6
    supply_score = _clamp(supply_base + foreign_boost + inst_boost)

    # ----- Weighted Final Score -----
    surge_score = (
        vol_score * 0.30 +
        mom_score * 0.25 +
        trend_score * 0.20 +
        osc_score * 0.15 +
        supply_score * 0.10
    )
    features.surge_score = round(_clamp(surge_score), 1)

    # ----- High / Medium / Low 라벨링 -----
    if features.surge_score >= 72.0:
        features.surge_label = "High"
    elif features.surge_score >= 54.0:
        features.surge_label = "Medium"
    else:
        features.surge_label = "Low"

    # ----- 고품질 한국어 reason_tags (2~5개) -----
    tags: List[str] = []

    # Volume
    if features.volume_explosion or vol_score >= 82:
        tags.append(f"거래량 {features.volume_ratio:.1f}배 폭발")
    elif vol_score >= 68 or features.volume_spike:
        tags.append(f"거래량 {features.volume_ratio:.1f}배 급증")
    elif features.volume_ratio >= 1.35:
        tags.append(f"거래량 {features.volume_ratio:.1f}배 증가")

    # Momentum
    if abs(features.five_day_return) >= 4.5 or mom_score >= 72:
        tags.append(f"5일 수익률 {features.five_day_return:+.1f}%")
    elif abs(features.ten_day_return) >= 6.0:
        tags.append(f"10일 수익률 {features.ten_day_return:+.1f}%")

    # Trend
    if features.above_ma20 and features.above_ma5 and trend_score >= 68:
        tags.append("주가 20일선 상향 돌파")
    elif features.above_ma60 and trend_score >= 60:
        tags.append("60일선 지지 확인")

    # Oscillator
    if features.rsi_14 >= 68 and osc_score >= 55:
        tags.append("RSI 상승 탄력")
    elif features.rsi_14 <= 32:
        tags.append("RSI 과매도권 반등 시도")
    if features.macd_hist > 0.3:
        tags.append("MACD 양전환")

    # Supply
    if features.foreign_netbuy > 150_000_000:
        tags.append("외국인 연속 순매수")
    elif features.foreign_netbuy < -200_000_000:
        tags.append("외국인 매도 우위")
    if features.inst_netbuy > 200_000_000:
        tags.append("기관 대규모 매수")

    if len(tags) < 2:
        if features.surge_score >= 60:
            tags.append("종합 모멘텀 양호")
        else:
            tags.append("기술적 수급 균형")

    features.reason_tags = tags[:5]

    # ----- 간단 추천 문구 -----
    if features.surge_label == "High":
        features.recommendation = "익일 급등 가능성 높음. 단기 집중 모니터링 추천."
    elif features.surge_label == "Medium":
        features.recommendation = "모멘텀 양호. 추가 상승 여력 관찰 필요."
    else:
        features.recommendation = "급등 신호 미약. 보수적 접근 또는 관망 권장."

    return features


# =============================================================================
# SurgeScore v2 (plan_v2.md 기반)
# =============================================================================

def compute_surge_score_v2(features: StockFeatures) -> StockFeatures:
    """
    v2 SurgeScore 계산
    - Supply 35% (강조)
    - Momentum 25%
    - Trend 20%
    - Oscillator 10%
    - Volume 5%
    - News 5% (현재는 0 처리)
    - T+1 / T+2 / T+3 신뢰도 분리 생성
    """
    if _USE_V2_CONFIG:
        weights = get_weights()
        supply_cfg = SUPPLY
        mom_cfg = MOMENTUM
    else:
        # fallback 기본값
        weights = type('obj', (object,), {'supply':35, 'momentum':25, 'trend':20, 'oscillator':10, 'volume':5, 'news':5})()
        supply_cfg = type('obj', (object,), {'consecutive_days_weight':4.0, 'foreign_3d_scale':3.0, 'inst_3d_scale':2.0, 'short_squeeze_bonus':10.0})()
        mom_cfg = type('obj', (object,), {'five_day_weight':80.0, 'recent_2d_positive_bonus':3.0})()

    # 1. Supply Score (0~35)
    supply_score = 0.0
    # 연속 방향성
    supply_score += features.foreign_consecutive_days * supply_cfg.consecutive_days_weight
    supply_score += features.inst_consecutive_days * (supply_cfg.consecutive_days_weight * 0.6)

    # 3일 누적
    supply_score += (features.foreign_netbuy_3d / 1_000_000_000) * supply_cfg.foreign_3d_scale
    supply_score += (features.inst_netbuy_3d / 1_000_000_000) * supply_cfg.inst_3d_scale

    # 기존 1일 데이터로 약간 보완 (하위 호환)
    if features.foreign_netbuy > 200_000_000:
        supply_score += 4
    if features.inst_netbuy > 300_000_000:
        supply_score += 3

    supply_score = _clamp(supply_score, 0, 35)

    # 2. Momentum Score (0~25)
    mom_raw = (features.five_day_return * 0.7 + features.ten_day_return * 0.3)
    momentum_score = 50.0 + mom_raw * (mom_cfg.five_day_weight / 20)
    if features.five_day_return > 0 and features.ten_day_return > 0:
        momentum_score += mom_cfg.recent_2d_positive_bonus
    momentum_score = _clamp(momentum_score, -5, 25)

    # 3. Trend/MA Score (0~20)
    trend_score = 0.0
    if features.above_ma5:  trend_score += 6
    if features.above_ma20: trend_score += 7
    if features.above_ma60: trend_score += 7
    trend_score = _clamp(trend_score + features.trend_strength * 8, 0, 20)

    # 4. Oscillator (0~10)
    rsi = features.rsi_14
    osc_score = 5.0
    if 48 < rsi < 72 and features.macd_hist > 0:
        osc_score = 10.0
    elif rsi < 35:
        osc_score = 7.0
    elif rsi > 78:
        osc_score = 2.0
    osc_score = _clamp(osc_score, 0, 10)

    # 5. Volume Bonus (0~5) - 필터 역할
    volume_bonus = 0.0
    if features.volume_ratio > 1.2:
        volume_bonus = min(5.0, (features.volume_ratio - 1.2) * 2.5)

    # 6. News (현재 0, 추후 sentiment 연결)
    news_score = 0.0

    # 최종 점수
    raw_score = (
        supply_score +
        momentum_score +
        trend_score +
        osc_score +
        volume_bonus +
        news_score
    )
    features.surge_score = round(_clamp(raw_score, 0, 100), 1)

    # 라벨링 (v2 기준 약간 조정)
    if features.surge_score >= 70:
        features.surge_label = "High"
    elif features.surge_score >= 52:
        features.surge_label = "Medium"
    else:
        features.surge_label = "Low"

    # === T+1 / T+2 / T+3 신뢰도 ===
    # T+1: 수급 + 단기 반응 중심
    features.confidence_t1 = round(_clamp(
        (supply_score / 35) * 55 +
        (osc_score / 10) * 25 +
        (momentum_score / 25) * 20
    ), 1)

    # T+2: 메인 (종합 점수 기반)
    features.confidence_t2 = features.surge_score

    # T+3: 추세 중심
    features.confidence_t3 = round(_clamp(
        (trend_score / 20) * 60 +
        (momentum_score / 25) * 40
    ), 1)

    # 고품질 한국어 reason_tags (v2 버전)
    tags: List[str] = []

    if features.foreign_consecutive_days >= 2:
        tags.append(f"외국인 {features.foreign_consecutive_days}일 연속 매수")
    elif features.foreign_consecutive_days <= -2:
        tags.append(f"외국인 {abs(features.foreign_consecutive_days)}일 연속 매도")

    if features.foreign_netbuy_3d > 300_000_000:
        tags.append("3일 외국인 대규모 순매수")
    if features.inst_netbuy_3d > 400_000_000:
        tags.append("3일 기관 강한 매수")

    if abs(features.five_day_return) >= 4:
        tags.append(f"5일 수익률 {features.five_day_return:+.1f}%")

    if features.above_ma20 and features.above_ma5:
        tags.append("20일선 상향 돌파")

    if features.macd_hist > 0.2:
        tags.append("MACD 양전환")

    if features.volume_ratio > 2.0:
        tags.append(f"거래량 {features.volume_ratio:.1f}배 급증")

    if len(tags) < 2:
        tags.append("수급 모멘텀 균형" if features.surge_score >= 55 else "관망 구간")

    features.reason_tags = tags[:5]

    # 추천 문구
    if features.surge_label == "High":
        features.recommendation = "T+2 중심 강한 후보. 수급 지속 여부 확인 추천."
    elif features.surge_label == "Medium":
        features.recommendation = "T+2~3 분할 접근 가능. 추가 확인 필요."
    else:
        features.recommendation = "보수적 관망. 더 나은 수급 신호 대기."

    return features


def build_analysis_result(stocks: List[StockFeatures], target_date: str, use_v2: bool = True) -> AnalysisResult:
    """전체 결과 빌드. use_v2=True 시 v2 로직 사용 (기본)"""
    next_day = get_next_trading_day(target_date)

    processed: List[StockFeatures] = []
    scorer = compute_surge_score_v2 if use_v2 else compute_surge_score

    for stock in stocks:
        processed.append(scorer(stock))

    total_vol = sum(s.volume for s in processed)
    avg_vr = sum(s.volume_ratio for s in processed) / max(1, len(processed))
    high_count = sum(1 for s in processed if s.surge_label == "High")

    return AnalysisResult(
        target_date=target_date,
        next_trading_day=next_day,
        stocks=processed,
        total_volume=total_vol,
        avg_volume_ratio=round(avg_vr, 2),
        high_surge_count=high_count
    )

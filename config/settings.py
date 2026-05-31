"""
v2 마이그레이션 설정 파일
모든 가중치, 필터 임계값, 키워드 사전 등을 중앙에서 관리합니다.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class SurgeScoreWeights:
    """SurgeScore v2 가중치 (총 100점)"""
    supply: float = 35.0      # 수급 (외국인/기관 연속성 + 누적)
    momentum: float = 25.0    # 모멘텀 (5일/2일 수익률 중심)
    trend: float = 20.0       # 추세/이동평균
    oscillator: float = 10.0  # RSI + MACD
    volume: float = 5.0       # 거래량 (필터 통과 후 보너스)
    news: float = 5.0         # 뉴스/공시 (경량)


@dataclass
class Filters:
    """후보 필터링 기준"""
    # 유동성 필터 (screener 단계에서 사용)
    min_trading_value: int = 5_000_000_000      # 일 거래대금 50억 이상

    # 거래량 최소 조건 (v2에서는 필터 역할만)
    min_volume_ratio: float = 1.2               # vol_ratio 1.2 이상이어야 후보 자격

    # 수급 필터 (초기 후보 압축용)
    require_positive_supply_3d: bool = True     # 외국인 or 기관 3일 누적 순매수 양수


@dataclass
class SupplySettings:
    """수급 관련 파라미터"""
    consecutive_days_weight: float = 4.0        # 연속 순매수 일수당 점수
    foreign_3d_scale: float = 3.0               # 3일 누적 외국인 / 10억 * 가중치
    inst_3d_scale: float = 2.0                  # 3일 누적 기관 / 10억 * 가중치

    # 숏스퀴즈 보너스
    short_squeeze_bonus: float = 10.0


@dataclass
class MomentumSettings:
    """모멘텀 관련 파라미터"""
    five_day_weight: float = 80.0
    recent_2d_positive_bonus: float = 3.0


@dataclass
class ShortSettings:
    """공매도 분석 파라미터"""
    high_short_ratio_threshold: float = 3.0     # 공매도 잔고 비율 3% 이상
    squeeze_volume_ratio_threshold: float = 2.0 # + 거래량 2배 이상 → 숏스퀴즈 신호


# 뉴스/공시 키워드 사전 (v2 경량 방식)
HOJAE_KEYWORDS: List[str] = [
    "수주", "계약", "신제품", "흑자전환", "목표가 상향", "신고가",
    "외국인 매수", "기관 매수", "실적 개선", "호실적", "M&A", "지분 인수",
    "배당", "자사주 매입", "신규 수주", "수출 증가"
]

AKJAE_KEYWORDS: List[str] = [
    "적자", "횡령", "소송", "계약해지", "목표가 하향", "매도",
    "실적 악화", "적자전환", "감사 의견 거절", "상장폐지 우려",
    "유상증자", "CB 발행", "공매도 증가"
]


# 전역 설정 인스턴스
WEIGHTS = SurgeScoreWeights()
FILTERS = Filters()
SUPPLY = SupplySettings()
MOMENTUM = MomentumSettings()
SHORT = ShortSettings()


def get_weights() -> SurgeScoreWeights:
    """현재 가중치 반환 (추후 동적 로딩 가능)"""
    return WEIGHTS


def get_filters() -> Filters:
    return FILTERS

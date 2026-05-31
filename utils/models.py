"""
Shared data models for the KOSPI Top Volume Analyzer.
Used across fetcher, analyzer, predictor, and UI.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class StockFeatures:
    """한 종목의 모든 분석 결과 (기술적 지표 + 수급 + 예측 점수)"""
    # 기본 정보
    ticker: str
    name: str
    target_date: str                  # 분석 기준일 YYYYMMDD
    close: float
    volume: int
    volume_ratio: float               # 오늘 거래량 / 20일 평균

    # 기술적 지표
    ma5: float
    ma20: float
    ma60: float
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float

    # 모멘텀 / 추세
    five_day_return: float            # 최근 5영업일 수익률 (%)
    ten_day_return: float
    above_ma5: bool
    above_ma20: bool
    above_ma60: bool
    trend_strength: float             # -1.0 ~ +1.0 (강한 하락 ~ 강한 상승)

    # 거래량 분석
    volume_spike: bool                # volume_ratio > 2.0
    volume_explosion: bool            # volume_ratio > 3.0

    # 수급 (pykrx investor) - v1 호환 필드
    foreign_netbuy: int = 0           # 외국인 순매수 금액 (원) - 당일
    inst_netbuy: int = 0              # 기관합계 순매수 금액 (원) - 당일
    netbuy_score: float = 0.0         # 수급 기여 점수 (v1)

    # === v2 확장 필드 (plan_v2.md) ===
    # 3일 누적 수급
    foreign_netbuy_3d: int = 0
    inst_netbuy_3d: int = 0
    foreign_consecutive_days: int = 0   # 양수=연속 매수, 음수=연속 매도
    inst_consecutive_days: int = 0

    # 공매도 (v2)
    short_balance_ratio: float = 0.0    # 공매도 잔고 비율 (%)
    short_balance_change: float = 0.0   # 전일 대비 변화율

    # 뉴스/공시 (v2)
    news_sentiment_score: float = 0.0   # -1.0 ~ +1.0
    dart_disclosure_flag: bool = False  # 최근 주요 공시 존재 여부

    # 다기간 신뢰도 (v2)
    confidence_t1: float = 0.0          # T+1 신뢰도
    confidence_t2: float = 0.0          # T+2 신뢰도 (메인)
    confidence_t3: float = 0.0          # T+3 신뢰도

    # 예측 결과
    surge_score: float = 0.0            # 0 ~ 100
    surge_label: str = "Low"            # High / Medium / Low
    reason_tags: List[str] = field(default_factory=list)
    recommendation: str = ""

    # 메타
    rank: int = 0                       # (필터링 후) 순위


@dataclass
class AnalysisResult:
    """전체 분석 결과 컨테이너"""
    target_date: str
    next_trading_day: str
    stocks: List[StockFeatures]
    total_volume: int = 0
    avg_volume_ratio: float = 0.0
    high_surge_count: int = 0

    @property
    def top5(self) -> List[StockFeatures]:
        return sorted(self.stocks, key=lambda s: s.surge_score, reverse=True)[:5]

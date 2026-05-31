"""
v2 Backtester (최소 버전)
plan_v2.md 기반: Rolling IC, Top5 적중률, Sharpe 계산

현재는 historical_data를 받아 메트릭을 계산하는 형태로 설계.
추후 실제 과거 데이터 수집 로직과 연결 예정.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
import numpy as np

try:
    from scipy.stats import spearmanr
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False
    print("[backtest] scipy가 설치되어 있지 않습니다. IC 계산이 비활성화됩니다. 'pip install scipy' 후 재시작하세요.")


@dataclass
class BacktestResult:
    """백테스트 결과"""
    n_days: int

    # Information Coefficient (Spearman)
    ic_t1: float
    ic_t2: float
    ic_t3: float

    # Top5 성과 (T+2 중심)
    hit_rate_t2: float          # +3% 이상 상승 비율
    sharpe_t2: float
    avg_return_top5_t2: float   # Top5 평균 수익률 (T+2)

    # 기타
    avg_return_t2: float        # 전체 후보 평균 T+2 수익률


@dataclass
class DailyResult:
    """하루 단위 결과 (백테스트 입력용)"""
    date: str
    scores: List[float]                    # 해당일 모든 종목의 SurgeScore
    future_t1_returns: List[float]         # T+1 실제 수익률 (%)
    future_t2_returns: List[float]         # T+2 실제 수익률 (%)
    future_t3_returns: List[float]         # T+3 실제 수익률 (%)
    top5_indices: Optional[List[int]] = None  # 미리 계산된 Top5 인덱스 (선택)


class RollingBacktester:
    """
    Rolling 백테스트 실행기 (최소 구현)

    사용 예시:
        backtester = RollingBacktester(window=60)
        result = backtester.run_rolling_backtest(daily_results)
    """

    def __init__(self, window: int = 60, hit_threshold: float = 0.03):
        self.window = window
        self.hit_threshold = hit_threshold

    def compute_ic(self, scores: List[float], returns: List[float]) -> float:
        """Spearman IC 계산"""
        if len(scores) < 5:
            return 0.0
        if not _HAS_SCIPY:
            return 0.0  # scipy 미설치 시 IC 계산 불가
        try:
            corr, _ = spearmanr(scores, returns)
            return float(corr) if not np.isnan(corr) else 0.0
        except Exception:
            return 0.0

    def compute_hit_rate(self, returns: List[float]) -> float:
        """Top5 중 threshold 이상 상승한 비율"""
        if not returns:
            return 0.0
        hits = sum(1 for r in returns if r >= self.hit_threshold)
        return hits / len(returns)

    def compute_sharpe(self, returns: List[float]) -> float:
        """단순 Sharpe (무위험금리 0 가정)"""
        if len(returns) < 2:
            return 0.0
        ret = np.array(returns) / 100.0  # % → decimal
        std = np.std(ret)
        if std == 0:
            return 0.0
        return float(np.mean(ret) / std)

    def run_rolling_backtest(
        self,
        daily_results: List[DailyResult]
    ) -> BacktestResult:
        """
        Rolling 백테스트 실행

        daily_results: 과거 날짜 순으로 정렬된 DailyResult 리스트
        """
        if len(daily_results) < self.window + 3:
            return BacktestResult(
                n_days=0, ic_t1=0, ic_t2=0, ic_t3=0,
                hit_rate_t2=0, sharpe_t2=0, avg_return_top5_t2=0,
                avg_return_t2=0
            )

        ics_t1, ics_t2, ics_t3 = [], [], []
        top5_t2_returns = []
        all_t2_returns = []

        for i in range(self.window, len(daily_results)):
            window_data = daily_results[i - self.window : i]

            # 최근 window일 동안의 score와 T+2 수익률로 IC 계산
            window_scores = []
            window_t2 = []
            for d in window_data:
                if d.scores and d.future_t2_returns:
                    window_scores.extend(d.scores)
                    window_t2.extend(d.future_t2_returns)

            if len(window_scores) > 10:
                ics_t1.append(self.compute_ic(window_scores, [r for d in window_data for r in d.future_t1_returns]))
                ics_t2.append(self.compute_ic(window_scores, window_t2))
                ics_t3.append(self.compute_ic(window_scores, [r for d in window_data for r in d.future_t3_returns]))

            # 오늘 Top5 성과
            today = daily_results[i]
            if today.scores and today.future_t2_returns:
                # Top5 선정 (점수 높은 순)
                sorted_idx = sorted(range(len(today.scores)), key=lambda x: today.scores[x], reverse=True)[:5]
                top5_returns = [today.future_t2_returns[j] for j in sorted_idx if j < len(today.future_t2_returns)]
                top5_t2_returns.extend(top5_returns)

                # 전체 평균
                all_t2_returns.extend(today.future_t2_returns)

        # 집계
        n = len(ics_t2)
        if n == 0:
            return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0)

        avg_ic_t1 = float(np.mean(ics_t1)) if ics_t1 else 0.0
        avg_ic_t2 = float(np.mean(ics_t2))
        avg_ic_t3 = float(np.mean(ics_t3)) if ics_t3 else 0.0

        hit_rate = self.compute_hit_rate(top5_t2_returns)
        sharpe = self.compute_sharpe(top5_t2_returns)
        avg_top5_ret = float(np.mean(top5_t2_returns)) if top5_t2_returns else 0.0
        avg_all_ret = float(np.mean(all_t2_returns)) if all_t2_returns else 0.0

        return BacktestResult(
            n_days=n,
            ic_t1=round(avg_ic_t1, 4),
            ic_t2=round(avg_ic_t2, 4),
            ic_t3=round(avg_ic_t3, 4),
            hit_rate_t2=round(hit_rate, 4),
            sharpe_t2=round(sharpe, 3),
            avg_return_top5_t2=round(avg_top5_ret, 3),
            avg_return_t2=round(avg_all_ret, 3),
        )


# 편의 함수
def create_daily_result_from_features(
    date: str,
    features_list: List,
    future_t1: List[float],
    future_t2: List[float],
    future_t3: List[float],
) -> DailyResult:
    """StockFeatures 리스트로부터 DailyResult 생성 (편의 함수)"""
    scores = [f.surge_score for f in features_list]
    return DailyResult(
        date=date,
        scores=scores,
        future_t1_returns=future_t1,
        future_t2_returns=future_t2,
        future_t3_returns=future_t3,
    )

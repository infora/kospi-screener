"""
v2 Historical Backtest using Screener (실제 데이터 기반)

screener 결과를 이용해 과거 특정 기간 동안의 백테스트를 수행합니다.
"""

from typing import List, Optional
from datetime import datetime, timedelta
import pandas as pd
import time

from data.screener import get_kospi_universe
from data.fetcher import get_ohlcv_history, get_latest_trading_day, _resolve_target_date
from analysis.analyzer import batch_analyze
from analysis.predictor import build_analysis_result
from backtest.backtester import DailyResult, create_daily_result_from_features
from utils.helpers import format_date_kr


def run_historical_backtest_with_screener(
    end_date: Optional[str] = None,
    lookback_days: int = 40,
    max_candidates_per_day: int = 50,
    use_screener: bool = True,
    verbose: bool = True,
) -> List[DailyResult]:
    """
    screener 기반 실제 히스토리컬 백테스트 실행 (최소 실행 가능 버전)

    Args:
        end_date: 백테스트 종료일 (YYYYMMDD). None이면 최근 영업일
        lookback_days: 몇 영업일 전까지 백테스트할지
        max_candidates_per_day: 매일 screener에서 가져올 최대 종목 수
        use_screener: True면 screener 사용, False면 기존 거래량 Top30 사용 (비교용)
        verbose: 진행 상황 출력 여부

    Returns:
        List[DailyResult] — RollingBacktester에 바로 넣을 수 있는 형태
    """
    resolved_end = _resolve_target_date(end_date)
    end_dt = datetime.strptime(resolved_end, "%Y%m%d")

    if verbose:
        print(f"[historical_backtest] 백테스트 시작: ~{resolved_end} (최근 {lookback_days}거래일)")

    daily_results: List[DailyResult] = []
    current_date = end_dt

    # 거래일 리스트 미리 생성 (최근 lookback_days + 여유)
    trading_days = []
    temp_date = end_dt
    while len(trading_days) < lookback_days + 10:
        if temp_date.weekday() < 5:
            trading_days.append(temp_date.strftime("%Y%m%d"))
        temp_date -= timedelta(days=1)
    trading_days = sorted(trading_days, reverse=True)[:lookback_days]

    for idx, date_str in enumerate(trading_days):
        try:
            if verbose:
                print(f"  [{idx+1}/{len(trading_days)}] {date_str} 처리 중...")

            # 1. 해당일 후보 선정
            if use_screener:
                candidates_df = get_kospi_universe(
                    target_date=date_str,
                    max_candidates=max_candidates_per_day,
                    include_etf=False,
                )
            else:
                # v1 비교용: 기존 거래량 Top 방식
                from data.fetcher import get_kospi_top30_volume
                candidates_df = get_kospi_top30_volume(target_date=date_str, include_etf=False)
                if not candidates_df.empty:
                    candidates_df = candidates_df.head(max_candidates_per_day)

            if candidates_df is None or candidates_df.empty:
                if verbose:
                    print(f"    → 후보 없음, 스킵")
                continue

            tickers = candidates_df["ticker"].tolist()

            # 2. OHLCV 수집 (미래 수익률 계산을 위해 +5일 여유)
            ohlcv_dict = get_ohlcv_history(tickers, date_str, lookback_days=10)

            # 3. 분석 + v2 점수 계산
            tickers_info = [
                {"ticker": row["ticker"], "name": row["name"], "rank": i+1}
                for i, row in candidates_df.iterrows()
            ]

            features_list = batch_analyze(
                tickers_info, ohlcv_dict, {}, date_str, enrich_supply=True
            )
            result = build_analysis_result(features_list, date_str, use_v2=True)

            # 4. 미래 수익률 계산 (T+1, T+2, T+3)
            t1_returns, t2_returns, t3_returns = _calculate_future_returns(
                result.stocks, ohlcv_dict, date_str
            )

            # 5. DailyResult 생성
            daily = create_daily_result_from_features(
                date=date_str,
                features_list=result.stocks,
                future_t1=t1_returns,
                future_t2=t2_returns,
                future_t3=t3_returns,
            )
            daily_results.append(daily)

            if verbose:
                print(f"    → {len(result.stocks)}종목 분석 완료")

            # KRX 부하 방지
            time.sleep(0.15)

        except Exception as e:
            if verbose:
                print(f"    → {date_str} 처리 실패: {str(e)[:80]}")
            continue

    if verbose:
        print(f"\n[historical_backtest] 완료: 총 {len(daily_results)}일 데이터 생성")

    return daily_results


def _calculate_future_returns(stocks, ohlcv_dict, base_date_str):
    """각 종목의 T+1, T+2, T+3 수익률 계산"""
    t1, t2, t3 = [], [], []

    base_dt = datetime.strptime(base_date_str, "%Y%m%d")

    for stock in stocks:
        ticker = stock.ticker
        df = ohlcv_dict.get(ticker)
        if df is None or df.empty or len(df) < 5:
            t1.append(0.0)
            t2.append(0.0)
            t3.append(0.0)
            continue

        try:
            # base_date 이후 가장 가까운 날짜부터 미래 수익률 계산
            future_df = df[df.index > pd.Timestamp(base_dt)].head(3)

            if len(future_df) == 0:
                t1.append(0.0); t2.append(0.0); t3.append(0.0)
                continue

            base_close = stock.close
            closes = future_df["close"].values

            r1 = ((closes[0] / base_close) - 1) * 100 if len(closes) >= 1 else 0.0
            r2 = ((closes[1] / base_close) - 1) * 100 if len(closes) >= 2 else r1
            r3 = ((closes[2] / base_close) - 1) * 100 if len(closes) >= 3 else r2

            t1.append(round(r1, 2))
            t2.append(round(r2, 2))
            t3.append(round(r3, 2))

        except Exception:
            t1.append(0.0); t2.append(0.0); t3.append(0.0)

    return t1, t2, t3


# 편의 실행 함수 (Streamlit 등에서 사용하기 좋게)
def run_and_evaluate_backtest(
    lookback_days: int = 40,
    use_screener: bool = True,
    verbose: bool = False,
):
    """
    백테스트를 실행하고 RollingBacktester로 평가한 결과를 바로 반환
    """
    from backtest.backtester import RollingBacktester

    daily_results = run_historical_backtest_with_screener(
        lookback_days=lookback_days,
        use_screener=use_screener,
        verbose=verbose,
    )

    if not daily_results:
        print("[historical_backtest] 백테스트 데이터가 충분하지 않습니다. (데이터 부족 또는 조회 실패)")
        return None, None

    backtester = RollingBacktester(window=min(30, len(daily_results) - 1))
    result = backtester.run_rolling_backtest(daily_results)
    return result, daily_results

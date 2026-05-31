"""
v2 후보 종목 스크리너 (plan_v2.md 기반)

기존 v1의 "거래량 상위 30 고정" 방식을 대체하는 핵심 모듈.

주요 로직:
1. 전체 KOSPI → 유동성 필터 (거래대금 기준)
2. 수급 1차 필터 (3일 누적 외국인/기관 순매수)
3. 모멘텀 1차 필터 (최근 5일 수익률)
4. 상위 N개 후보 반환 (보통 60~80종목)
"""

from typing import Optional
import pandas as pd
from datetime import datetime, timedelta
import time

from data.fetcher import (
    get_latest_trading_day,
    get_ohlcv_history,
    _resolve_target_date,
)
from utils.helpers import filter_common_stocks, safe_int, format_date_kr

# Lazy import for supply functions to avoid import-time errors if fetcher has issues
try:
    from data.fetcher import get_supply_demand
except ImportError:
    get_supply_demand = None


def get_kospi_universe(
    target_date: Optional[str] = None,
    min_trading_value: int = 5_000_000_000,        # 일 거래대금 50억 이상
    require_positive_supply_3d: bool = True,       # 3일 누적 수급 양수 필수
    min_5d_return: float = -3.0,                   # 5일 수익률 -3% 이상
    max_candidates: int = 80,
    include_etf: bool = False,
) -> pd.DataFrame:
    """
    v2 스타일 후보 종목 유니버스 추출

    Returns:
        DataFrame with columns:
        ['ticker', 'name', 'close', 'volume', 'trading_value', 'rank',
         'foreign_netbuy_3d', 'inst_netbuy_3d', 'five_day_return']
    """
    resolved = _resolve_target_date(target_date)
    print(f"[screener] get_kospi_universe 기준일: {resolved} ({format_date_kr(resolved)})")

    # 1. 전체 시장 데이터 가져오기 (market cap 데이터 활용)
    try:
        from pykrx import stock

        # 시장 전체 데이터 (거래대금 포함)
        cap_df = stock.get_market_cap(resolved, market="KOSPI")
        if cap_df is None or cap_df.empty:
            raise ValueError("시장 데이터 조회 실패")

        cap_df = cap_df.reset_index()
        cap_df["ticker"] = cap_df["티커"].astype(str).str.zfill(6)
        cap_df["name"] = cap_df["티커"].apply(
            lambda x: stock.get_market_ticker_name(str(x).zfill(6)) or str(x)
        )
        cap_df["close"] = cap_df["종가"]
        cap_df["volume"] = cap_df["거래량"]
        cap_df["trading_value"] = cap_df["거래대금"]

        # ETF/ETN 필터
        if not include_etf:
            cap_df = filter_common_stocks(cap_df)

        # 유동성 필터
        cap_df = cap_df[cap_df["trading_value"] >= min_trading_value].copy()

        if cap_df.empty:
            print("[screener] 유동성 필터 후 종목이 없습니다.")
            return pd.DataFrame()

        tickers = cap_df["ticker"].tolist()
        print(f"[screener] 유동성 필터 통과: {len(tickers)} 종목")

    except Exception as e:
        print(f"[screener] pykrx 시장 데이터 조회 실패: {e}")
        # Fallback: 주요 종목 리스트 사용 (개발용)
        return _get_fallback_universe(resolved, min_trading_value, max_candidates)

    # 2. 수급 데이터 (3일) 조회
    supply_data = {t: {"foreign_netbuy_3d": 0, "inst_netbuy_3d": 0} for t in tickers}
    if get_supply_demand is not None:
        try:
            supply_data = get_supply_demand(tickers, resolved, days=3)
        except Exception as e:
            print(f"[screener] 수급 데이터 조회 실패: {e}")

    # 3. OHLCV 조회 (5일 수익률 계산용)
    try:
        ohlcv_dict = get_ohlcv_history(tickers, resolved, lookback_days=10)
    except Exception as e:
        print(f"[screener] OHLCV 조회 실패: {e}")
        ohlcv_dict = {}

    # 4. 필터링 + 점수 계산
    filtered = []
    for _, row in cap_df.iterrows():
        tkr = row["ticker"]

        supply = supply_data.get(tkr, {})
        foreign_3d = supply.get("foreign_netbuy_3d", 0)
        inst_3d = supply.get("inst_netbuy_3d", 0)

        # 수급 필터
        if require_positive_supply_3d:
            if foreign_3d <= 0 and inst_3d <= 0:
                continue

        # 5일 수익률 계산
        five_day_return = 0.0
        ohlcv = ohlcv_dict.get(tkr)
        if ohlcv is not None and len(ohlcv) >= 5:
            try:
                closes = ohlcv["close"].iloc[-5:]
                if closes.iloc[0] > 0:
                    five_day_return = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
            except Exception:
                pass

        # 모멘텀 필터
        if five_day_return < min_5d_return:
            continue

        # 수급 + 모멘텀 간단 복합 점수 (추후 screener 전용 점수로 발전 가능)
        supply_score = (foreign_3d + inst_3d * 0.7) / 1e9   # 10억 단위
        momentum_score = max(five_day_return, 0) * 0.3
        composite = supply_score + momentum_score

        filtered.append({
            "ticker": tkr,
            "name": row["name"],
            "close": row["close"],
            "volume": row["volume"],
            "trading_value": row["trading_value"],
            "foreign_netbuy_3d": foreign_3d,
            "inst_netbuy_3d": inst_3d,
            "five_day_return": round(five_day_return, 2),
            "composite_score": round(composite, 2),
        })

    if not filtered:
        print("[screener] 모든 필터 통과 종목 없음")
        return pd.DataFrame()

    df = pd.DataFrame(filtered)
    df = df.sort_values("composite_score", ascending=False).head(max_candidates).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    print(f"[screener] 최종 후보 {len(df)}종목 선정 완료")
    return df[["ticker", "name", "close", "volume", "trading_value", "rank",
               "foreign_netbuy_3d", "inst_netbuy_3d", "five_day_return"]]


def _get_fallback_universe(target_date: str, min_trading_value: int, max_candidates: int):
    """pykrx 실패 시 사용할 주요 종목 기반 fallback (개발/테스트용)"""
    from data.fetcher import KOSPI_MAJOR_CANDIDATES

    print("[screener] Fallback 모드 사용")

    # 간단히 주요 종목만 반환
    records = []
    for tkr in KOSPI_MAJOR_CANDIDATES[:max_candidates]:
        records.append({
            "ticker": tkr,
            "name": tkr,  # 실제 이름은 나중에 보완
            "close": 0,
            "volume": 0,
            "trading_value": min_trading_value + 1,
            "rank": len(records) + 1,
            "foreign_netbuy_3d": 0,
            "inst_netbuy_3d": 0,
            "five_day_return": 0.0,
        })

    return pd.DataFrame(records)


# =============================================================================
# Standalone Test
# =============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("data/screener.py - KOSPI Universe Screener Test (v2)")
    print("=" * 70)

    latest = get_latest_trading_day()
    print(f"\n기준일: {latest} ({format_date_kr(latest)})")

    df = get_kospi_universe(
        target_date=latest,
        min_trading_value=5_000_000_000,
        max_candidates=30,   # 테스트용으로 줄임
    )

    if not df.empty:
        print(f"\n최종 후보 {len(df)}종목")
        print(df.head(10).to_string(index=False))
    else:
        print("\n필터 통과 종목 없음")

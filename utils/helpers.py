"""
공통 헬퍼 함수 (날짜 처리, 포맷, 필터 등)
"""
from datetime import datetime, timedelta
from typing import Optional
import re


ETF_KEYWORDS = [
    "KODEX", "TIGER", "SOL", "RISE", "HANARO", "KBSTAR", "KINDEX",
    "ARIRANG", "파워", "ETN", "인버스", "레버리지", "2X", "3X",
    "선물", "국고채", "원유", "금", "은", "구리", "나스닥", "S&P"
]


def is_valid_trading_date(date_str: str) -> bool:
    """간단 검증 (실제 영업일 여부는 pykrx가 처리)"""
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        return d.weekday() < 5  # 월~금
    except:
        return False


def format_date_kr(date_str: str) -> str:
    """20260528 → 2026-05-28"""
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def filter_common_stocks(df):
    """
    ETF/ETN/레버리지 상품 제외 필터.
    pykrx get_market_cap 결과 DataFrame에 적용.
    """
    if df is None or df.empty:
        return df

    mask = ~df['종목명'].astype(str).apply(
        lambda x: any(kw.lower() in x.lower() for kw in ETF_KEYWORDS)
    )
    return df[mask].copy()


def get_next_trading_day(date_str: str) -> str:
    """간단 다음 영업일 (실제 공휴일 무시, pykrx 추천)"""
    d = datetime.strptime(date_str, "%Y%m%d")
    while True:
        d += timedelta(days=1)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

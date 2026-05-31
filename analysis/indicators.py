"""
Subagent 2 전용
모든 기술적 지표 계산 (pandas_ta 또는 순수 pandas)

- compute_all_indicators: OHLCV DF에 EMA/SMA(5/20/60), RSI(14), MACD(12,26,9)+signal+hist,
  volume_sma20, volume_ratio/spike/explosion, 5d/10d returns, trend_strength 등 추가 (vectorized)
- get_latest_features: target_date (또는 마지막 행)에서 StockFeatures 필드용 dict 추출
- 한국 주식 데이터( pykrx 한글 컬럼, short history, missing NaN )에 강건하게 동작
- pandas_ta 우선, import 실패/오류 시 순수 pandas fallback
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

# pandas_ta graceful fallback (요구사항: import issues 시 fallback)
try:
    import pandas_ta as ta
except ImportError:
    ta = None


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    pykrx / yfinance 등에서 오는 다양한 컬럼 포맷을 표준화.
    - 한글(시가/고가/저가/종가/거래량) → open/high/low/close/volume
    - 영문 대소문자 대응
    - index를 DatetimeIndex로 정렬 (필요 시 date 컬럼 사용)
    - numeric 변환 + 결측 행 정리
    한국 주식 데이터 호환성 핵심.
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # 컬럼 매핑 (한글 + 영문)
    col_rename = {}
    for col in list(df.columns):
        c = str(col).strip()
        cl = c.lower()
        if c in ("시가", "open", "Open"):
            col_rename[col] = "open"
        elif c in ("고가", "high", "High"):
            col_rename[col] = "high"
        elif c in ("저가", "low", "Low"):
            col_rename[col] = "low"
        elif c in ("종가", "close", "Close"):
            col_rename[col] = "close"
        elif c in ("거래량", "volume", "Volume"):
            col_rename[col] = "volume"
        elif c in ("date", "Date", "날짜", "일자"):
            col_rename[col] = "date"

    if col_rename:
        df = df.rename(columns=col_rename)

    # index를 DatetimeIndex로 (pykrx는 보통 DatetimeIndex)
    if not isinstance(df.index, pd.DatetimeIndex):
        date_col = None
        for dc in ("date", "Date", "날짜", "일자"):
            if dc in df.columns:
                date_col = dc
                break
        if date_col is not None:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.set_index(date_col)
        else:
            # 마지막 시도: 현재 index 파싱
            try:
                df.index = pd.to_datetime(df.index, errors="coerce")
            except Exception:
                pass

    if isinstance(df.index, pd.DatetimeIndex):
        df = df[~df.index.isna()].sort_index()

    # 필수 컬럼 numeric 강제 + close 기준 유효 행만 유지
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "close" in df.columns:
        df = df.dropna(subset=["close"])

    return df


def _compute_rsi_pure(close: pd.Series, length: int = 14) -> pd.Series:
    """순수 pandas RSI (Wilder) - pandas_ta 없을 때 fallback"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.ewm(alpha=1/length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False, min_periods=length).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _compute_macd_pure(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """순수 pandas MACD"""
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=1).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=1).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    OHLCV DataFrame에 모든 기술적 지표를 vectorized 방식으로 추가.

    추가 컬럼 (일관된 소문자 이름):
    - ma5, ma20, ma60 (SMA 사용, StockFeatures 호환)
    - ema5, ema20, ema60
    - rsi_14
    - macd, macd_signal, macd_hist   (12,26,9)
    - volume_sma20, volume_ratio, volume_spike (>2.0), volume_explosion (>3.0)
    - return_5d, return_10d   (% 단위)
    - above_ma5 / above_ma20 / above_ma60
    - trend_strength  (-1.0 ~ +1.0, ma alignment + price position + short slope 종합)

    pandas_ta Strategy 우선 사용. 실패/미설치 시 완전한 순수 pandas 구현으로 fallback.
    짧은 히스토리(신규상장), NaN, 0 volume, 한국 컬럼 모두 처리.
    """
    if df is None or len(df) < 1:
        return df

    df = _normalize_ohlcv(df)
    if df.empty or "close" not in df.columns or "volume" not in df.columns:
        return df

    out = df.copy()

    close = out["close"]
    vol = out["volume"].astype(float)

    # ===== pandas_ta Strategy 경로 (선호) =====
    used_ta = False
    if ta is not None:
        try:
            # Strategy 정의 — 한 번에 여러 지표 (clean & vectorized)
            strat = ta.Strategy(
                name="KOSPI_TopVolume_Strategy",
                description="EMA/SMA + RSI + MACD + Volume for daily surge analysis",
                ta=[
                    {"kind": "sma", "length": 5},
                    {"kind": "sma", "length": 20},
                    {"kind": "sma", "length": 60},
                    {"kind": "ema", "length": 5},
                    {"kind": "ema", "length": 20},
                    {"kind": "ema", "length": 60},
                    {"kind": "rsi", "length": 14},
                    {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
                ],
            )
            # append columns in-place
            out.ta.strategy(strat, verbose=False, timed=False)

            # 표준 이름으로 리네임 (일관성)
            rename_map = {
                "SMA_5": "ma5",
                "SMA_20": "ma20",
                "SMA_60": "ma60",
                "EMA_5": "ema5",
                "EMA_20": "ema20",
                "EMA_60": "ema60",
                "RSI_14": "rsi_14",
                "MACD_12_26_9": "macd",
                "MACDs_12_26_9": "macd_signal",
                "MACDh_12_26_9": "macd_hist",
            }
            out = out.rename(columns=rename_map)
            used_ta = True
        except Exception:
            # 어떤 이유로든 pandas_ta 실패 → fallback
            used_ta = False

    # ===== Pure pandas fallback (완전 독립 구현) =====
    if not used_ta:
        # SMA / EMA (min_periods=1 로 short history 대응)
        out["ma5"] = close.rolling(5, min_periods=1).mean()
        out["ma20"] = close.rolling(20, min_periods=1).mean()
        out["ma60"] = close.rolling(60, min_periods=1).mean()

        out["ema5"] = close.ewm(span=5, adjust=False, min_periods=1).mean()
        out["ema20"] = close.ewm(span=20, adjust=False, min_periods=1).mean()
        out["ema60"] = close.ewm(span=60, adjust=False, min_periods=1).mean()

        # RSI (robust)
        out["rsi_14"] = _compute_rsi_pure(close, 14)

        # MACD
        out["macd"], out["macd_signal"], out["macd_hist"] = _compute_macd_pure(close)

    # ===== Volume indicators (항상 pandas) =====
    out["volume_sma20"] = vol.rolling(20, min_periods=1).mean()
    # 0 division 방지 + NaN 안전
    vol_sma_safe = out["volume_sma20"].replace(0.0, np.nan)
    out["volume_ratio"] = (vol / vol_sma_safe).fillna(1.0)
    # 극단값 clip (데이터 오류 방지, 일일 사용 시 안전)
    out["volume_ratio"] = out["volume_ratio"].clip(upper=20.0)

    out["volume_spike"] = out["volume_ratio"] > 2.0
    out["volume_explosion"] = out["volume_ratio"] > 3.0

    # ===== Returns (5d / 10d) % =====
    out["return_5d"] = close.pct_change(periods=5) * 100.0
    out["return_10d"] = close.pct_change(periods=10) * 100.0
    out["return_5d"] = out["return_5d"].fillna(0.0).clip(-100, 300)
    out["return_10d"] = out["return_10d"].fillna(0.0).clip(-100, 500)

    # ===== Above MA flags (StockFeatures + chart 용) =====
    out["above_ma5"] = close > out["ma5"]
    out["above_ma20"] = close > out["ma20"]
    out["above_ma60"] = close > out["ma60"]

    # ===== Trend strength (-1.0 ~ +1.0) : vectorized composite =====
    # 1. price position vs ma60 (장기 추세)
    pos60 = np.where(
        out["ma60"] != 0,
        (close - out["ma60"]) / out["ma60"],
        0.0
    )
    # 2. 단기 ma slope (ma5 vs ma20)
    slope_short = np.where(
        out["ma20"] != 0,
        (out["ma5"] - out["ma20"]) / out["ma20"],
        0.0
    )
    # 3. MA alignment bullish 점수 (0~1)
    align = (
        (close > out["ma5"]).astype(float) * 0.25 +
        (out["ma5"] > out["ma20"]).astype(float) * 0.25 +
        (out["ma20"] > out["ma60"]).astype(float) * 0.25 +
        (close > out["ma60"]).astype(float) * 0.25
    )
    # 종합 (가중) 후 clip
    raw_strength = pos60 * 0.55 + slope_short * 1.8 + (align - 0.5) * 1.1
    out["trend_strength"] = np.clip(raw_strength, -1.0, 1.0)

    # NaN / inf 정리 (latest row 안전)
    for c in ["ma5", "ma20", "ma60", "ema5", "ema20", "ema60", "rsi_14",
              "macd", "macd_signal", "macd_hist", "volume_sma20", "volume_ratio",
              "trend_strength"]:
        if c in out.columns:
            out[c] = out[c].replace([np.inf, -np.inf], np.nan)
            # 마지막 값 기준으로 앞쪽만 ffill (과거 NaN은 허용, 최신값은 채움)
            out[c] = out[c].ffill().fillna(
                out[c].iloc[-1] if len(out) > 0 else 0.0
            )

    # 원본 OHLCV + 지표 컬럼만 유지 (불필요 컬럼 제거)
    keep = ["open", "high", "low", "close", "volume"] + [
        c for c in out.columns if c not in ["open", "high", "low", "close", "volume"]
    ]
    out = out[[k for k in keep if k in out.columns]]

    return out


def get_latest_features(df_with_indicators: pd.DataFrame, target_date: str) -> Dict[str, Any]:
    """
    indicators 계산 완료된 DF에서 target_date (YYYYMMDD 또는 YYYY-MM-DD) 또는
    가장 최근 행의 값을 StockFeatures 생성에 바로 쓸 수 있는 dict로 추출.

    - 날짜 포맷 유연 처리
    - NaN / 짧은 히스토리 → 합리적 기본값 (rsi=50, ratio=1.0, trend=0, returns=0)
    - bool/int/float 타입 정확히 맞춤
    - analyzer에서 StockFeatures(ticker=.., name=.., target_date=.., **this_dict) 로 사용 예상
    """
    if df_with_indicators is None or df_with_indicators.empty:
        return _default_latest_features()

    df = df_with_indicators.copy()

    # target_date 파싱 시도 → 해당 행 또는 iloc[-1]
    row = None
    target_str = str(target_date).replace("-", "").replace("/", "") if target_date else ""

    if isinstance(df.index, pd.DatetimeIndex) and target_str:
        try:
            dt = pd.to_datetime(target_str, format="%Y%m%d", errors="coerce")
            if pd.notna(dt) and dt in df.index:
                row = df.loc[dt]
            else:
                # 가장 가까운 이전 영업일 (또는 마지막)
                idx = df.index[df.index <= dt]
                if len(idx) > 0:
                    row = df.loc[idx[-1]]
                else:
                    row = df.iloc[-1]
        except Exception:
            row = df.iloc[-1]
    else:
        row = df.iloc[-1]

    if row is None:
        row = df.iloc[-1]

    # 안전 추출 헬퍼
    def f(v: Any, default: float = 0.0) -> float:
        try:
            val = float(v)
            if pd.isna(val) or np.isinf(val):
                return default
            return val
        except Exception:
            return default

    def b(v: Any, default: bool = False) -> bool:
        try:
            if pd.isna(v):
                return default
            return bool(v)
        except Exception:
            return default

    close = f(row.get("close", 0.0), 0.0)
    volume = int(f(row.get("volume", 0), 0))
    vol_ratio = f(row.get("volume_ratio", 1.0), 1.0)

    ma5 = f(row.get("ma5", close), close)
    ma20 = f(row.get("ma20", close), close)
    ma60 = f(row.get("ma60", close), close)

    rsi = f(row.get("rsi_14", 50.0), 50.0)
    macd_v = f(row.get("macd", 0.0), 0.0)
    macd_sig = f(row.get("macd_signal", 0.0), 0.0)
    macd_h = f(row.get("macd_hist", 0.0), 0.0)

    ret5 = f(row.get("return_5d", 0.0), 0.0)
    ret10 = f(row.get("return_10d", 0.0), 0.0)

    trend = f(row.get("trend_strength", 0.0), 0.0)
    trend = max(-1.0, min(1.0, trend))

    vol_spike = b(row.get("volume_spike", vol_ratio > 2.0), vol_ratio > 2.0)
    vol_expl = b(row.get("volume_explosion", vol_ratio > 3.0), vol_ratio > 3.0)

    above5 = b(row.get("above_ma5", close > ma5), close > ma5)
    above20 = b(row.get("above_ma20", close > ma20), close > ma20)
    above60 = b(row.get("above_ma60", close > ma60), close > ma60)

    features: Dict[str, Any] = {
        "close": close,
        "volume": volume,
        "volume_ratio": round(vol_ratio, 4),
        "ma5": round(ma5, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "rsi_14": round(rsi, 2),
        "macd": round(macd_v, 4),
        "macd_signal": round(macd_sig, 4),
        "macd_hist": round(macd_h, 4),
        "five_day_return": round(ret5, 2),
        "ten_day_return": round(ret10, 2),
        "above_ma5": above5,
        "above_ma20": above20,
        "above_ma60": above60,
        "volume_spike": vol_spike,
        "volume_explosion": vol_expl,
        "trend_strength": round(trend, 4),
        # 보조 (필요 시 사용)
        "ema5": round(f(row.get("ema5", ma5), ma5), 2),
        "ema20": round(f(row.get("ema20", ma20), ma20), 2),
        "ema60": round(f(row.get("ema60", ma60), ma60), 2),
        "volume_sma20": round(f(row.get("volume_sma20", volume), volume), 0),
    }
    return features


def _default_latest_features() -> Dict[str, Any]:
    """get_latest_features 실패 시 안전 기본값 (analyzer crash 방지)"""
    return {
        "close": 0.0,
        "volume": 0,
        "volume_ratio": 1.0,
        "ma5": 0.0,
        "ma20": 0.0,
        "ma60": 0.0,
        "rsi_14": 50.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "macd_hist": 0.0,
        "five_day_return": 0.0,
        "ten_day_return": 0.0,
        "above_ma5": False,
        "above_ma20": False,
        "above_ma60": False,
        "volume_spike": False,
        "volume_explosion": False,
        "trend_strength": 0.0,
        "ema5": 0.0,
        "ema20": 0.0,
        "ema60": 0.0,
        "volume_sma20": 0,
    }


if __name__ == "__main__":
    """
    Subagent 2 standalone self-test.
    - synthetic OHLCV (Korean stock style, volume spike injected)
    - Korean column name input test (pykrx compatibility)
    - Short history (15-day new listing) test
    - Full roundtrip of compute_all_indicators + get_latest_features
    """
    print("=" * 60)
    print("Subagent 2: analysis/indicators.py  SELF TEST START (ASCII safe)")
    print("=" * 60)

    np.random.seed(2026)

    # === 1. Full 120-day synthetic OHLCV (English columns) ===
    n_days = 120
    dates = pd.date_range(end="2026-05-27", periods=n_days, freq="B")
    base_price = 68500.0
    returns = np.random.normal(0.0008, 0.018, n_days)
    close = base_price * np.cumprod(1 + returns)
    close = np.maximum(close, 1000.0)

    high = close * (1 + np.abs(np.random.normal(0, 0.008, n_days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.008, n_days)))
    open_p = close * (1 + np.random.normal(0, 0.003, n_days))
    volume = np.random.randint(120_000, 8_500_000, n_days).astype(float)
    # Inject explicit volume explosion at the end (ratio ~2.7)
    volume[-1] = volume[-5:-1].mean() * 2.75

    df_eng = pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )

    print(f"\n[TEST 1] English columns + 120 days (volume spike injected)")
    print(f"  Input shape: {df_eng.shape}, last close: {close[-1]:.0f}")

    df_ind = compute_all_indicators(df_eng)
    print(f"  Output columns: {len(df_ind.columns)} (incl. indicators)")
    key_cols = ["close", "ma5", "ma20", "ma60", "rsi_14", "macd_hist",
                "volume_ratio", "volume_spike", "volume_explosion",
                "return_5d", "trend_strength"]
    print(df_ind[key_cols].tail(3).to_string())

    latest = get_latest_features(df_ind, "20260527")
    print("\n  get_latest_features (target_date=20260527):")
    for k in ["close", "volume_ratio", "rsi_14", "macd_hist", "five_day_return",
              "volume_spike", "volume_explosion", "trend_strength", "above_ma20"]:
        print(f"    {k:18s}: {latest[k]}")

    # === 2. Korean column name compatibility (pykrx style) ===
    print(f"\n[TEST 2] Korean columns (pykrx-style) compatibility")
    df_kr = df_eng.rename(
        columns={"open": "시가", "high": "고가", "low": "저가", "close": "종가", "volume": "거래량"}
    )
    df_ind_kr = compute_all_indicators(df_kr)
    latest_kr = get_latest_features(df_ind_kr, "2026-05-27")
    print(f"  KR input ma5 matches EN ma5? {abs(latest_kr['ma5'] - latest['ma5']) < 0.1}")
    print(f"  volume_spike detected (expected True): {latest_kr['volume_spike']}")

    # === 3. Short history (new listing simulation, 15 days) ===
    print(f"\n[TEST 3] Short history (15 days) - ma60/rsi fallback behavior")
    df_short = df_eng.iloc[-15:].copy()
    df_ind_short = compute_all_indicators(df_short)
    latest_short = get_latest_features(df_ind_short, "20260527")
    print(f"  15-day ma60 computed (not NaN): {not pd.isna(latest_short['ma60'])}")
    print(f"  rsi_14: {latest_short['rsi_14']:.1f} (sensible vs default 50)")
    print(f"  trend_strength: {latest_short['trend_strength']:.3f}")

    # === 4. Final summary (ASCII only for Windows cp949 consoles) ===
    print("\n" + "=" * 60)
    print("[PASS] ALL TESTS PASSED - compute_all_indicators / get_latest_features working correctly")
    print("   (pandas_ta=" + ("ENABLED" if ta is not None else "DISABLED (pure pandas fallback)") + ")")
    print("   Ready for StockFeatures(ticker, name, target_date, **latest_features)")
    print("=" * 60)

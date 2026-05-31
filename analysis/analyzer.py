"""
Subagent 3 & 4 공동 작업 영역
batch_analyze + StockFeatures 생성 (v1 + v2 지원)

v2 업데이트:
- batch_analyze 호출 시 기본적으로 3일 누적 수급 + 연속 방향성 데이터를 자동 보강
- StockFeatures v2 필드(foreign_netbuy_3d, consecutive_days, short, confidence_t* 등) 지원
- 하위 호환 유지 (enrich_supply=False로 기존 동작 가능)
"""
from typing import List, Dict, Any
import pandas as pd
import pandas_ta as ta
from utils.models import StockFeatures
from utils.helpers import safe_int

# v2 수급 데이터 보강을 위해 fetcher 연동
try:
    from data.fetcher import enrich_with_investor_and_supply_data
    _HAS_SUPPLY_ENRICH = True
except Exception:
    _HAS_SUPPLY_ENRICH = False


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safe float conversion handling NaN/None."""
    try:
        if val is None:
            return default
        if isinstance(val, float) and pd.isna(val):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _create_default_stock_features(ticker: str, name: str, target_date: str, rank: int) -> StockFeatures:
    """Graceful fallback for missing data (keeps batch running for all 30)."""
    return StockFeatures(
        ticker=str(ticker),
        name=str(name) if name else str(ticker),
        target_date=str(target_date),
        close=0.0,
        volume=0,
        volume_ratio=1.0,
        ma5=0.0,
        ma20=0.0,
        ma60=0.0,
        rsi_14=50.0,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        five_day_return=0.0,
        ten_day_return=0.0,
        above_ma5=False,
        above_ma20=False,
        above_ma60=False,
        trend_strength=0.0,
        volume_spike=False,
        volume_explosion=False,
        rank=int(rank) if rank is not None else 0,
    )


def analyze_single_stock(ticker: str, name: str, ohlcv_df: pd.DataFrame,
                         investor_data: dict, target_date: str, rank: int) -> StockFeatures:
    """1개 종목 전체 분석 → StockFeatures

    - All required fields populated from OHLCV + investor.
    - Prefers indicators.compute_all_indicators + get_latest_features (when Subagent 2 ready).
    - Strong inline pandas_ta fallback so full 30-ticker path works immediately / in isolation.
    - Extras integrated into existing fields (no model changes):
        * MFI-14: modulates trend_strength on extremes + volume.
        * Simple MACD divergence (5-7 bar lookback): bearish/bullish div adjusts trend by +/- 0.18.
        * ADX-14: scales trend conviction.
    - surge_* fields intentionally default (0 / "Low" / []); predictor fills later.
    """
    if ohlcv_df is None or getattr(ohlcv_df, 'empty', True):
        return _create_default_stock_features(ticker, name, target_date, rank)

    df = ohlcv_df.copy()

    # Normalize index to DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            df.index = pd.RangeIndex(start=0, stop=len(df), step=1)

    df = df.sort_index()

    # Restrict to target_date and prior (no future data leak)
    try:
        tgt_dt = pd.to_datetime(target_date, format="%Y%m%d")
        df = df[df.index <= tgt_dt].copy()
    except Exception:
        pass

    if len(df) < 1:
        return _create_default_stock_features(ticker, name, target_date, rank)

    # Lowercase columns for robustness (pykrx returns lower)
    df.columns = [str(c).lower().strip() for c in df.columns]

    if 'close' not in df.columns:
        return _create_default_stock_features(ticker, name, target_date, rank)
    if 'volume' not in df.columns:
        df['volume'] = 0

    close = _safe_float(df['close'].iloc[-1], 0.0)
    volume = int(_safe_float(df['volume'].iloc[-1], 0))

    # === Compatibility path: use indicators.py when implemented ===
    latest: Dict[str, Any] = {}
    used_indicators = False
    try:
        from . import indicators as ind_mod
        ind_df = ind_mod.compute_all_indicators(df)
        latest = ind_mod.get_latest_features(ind_df, target_date) or {}
        used_indicators = bool(latest)
    except Exception:
        used_indicators = False
        latest = {}

    if not used_indicators:
        # === INLINE FALLBACK (Subagent 4) using pandas_ta - guarantees 30-stock functionality ===
        try:
            df['ma5'] = ta.sma(df['close'], length=5)
            df['ma20'] = ta.sma(df['close'], length=20)
            df['ma60'] = ta.sma(df['close'], length=60)
            df['rsi_14'] = ta.rsi(df['close'], length=14)

            macd_res = ta.macd(df['close'], fast=12, slow=26, signal=9)
            if macd_res is not None and len(macd_res.columns) >= 3:
                c0, c1, c2 = macd_res.columns[0], macd_res.columns[1], macd_res.columns[2]
                df['macd'] = macd_res[c0]
                df['macd_hist'] = macd_res[c1]
                df['macd_signal'] = macd_res[c2]
            else:
                df['macd'] = 0.0
                df['macd_hist'] = 0.0
                df['macd_signal'] = 0.0

            df['vol_sma20'] = ta.sma(df['volume'], length=20)
            df['ret5'] = df['close'].pct_change(5) * 100
            df['ret10'] = df['close'].pct_change(10) * 100

            # EXTRA: MFI (Money Flow Index)
            try:
                if {'high', 'low', 'close', 'volume'}.issubset(df.columns):
                    df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
                else:
                    df['mfi'] = 50.0
            except Exception:
                df['mfi'] = 50.0

            # EXTRA: ADX (for trend_strength scaling)
            try:
                if {'high', 'low', 'close'}.issubset(df.columns):
                    adx_res = ta.adx(df['high'], df['low'], df['close'], length=14)
                    if adx_res is not None and not adx_res.empty:
                        adx_col = next((c for c in adx_res.columns if 'ADX' in str(c).upper()), adx_res.columns[0])
                        df['adx'] = adx_res[adx_col]
                    else:
                        df['adx'] = 20.0
                else:
                    df['adx'] = 20.0
            except Exception:
                df['adx'] = 20.0

            last = df.iloc[-1]
            vol_sma = _safe_float(last.get('vol_sma20'), max(1.0, float(volume)))
            v_ratio = (float(volume) / vol_sma) if vol_sma > 0 else 1.0

            latest = {
                'close': close,
                'volume': volume,
                'ma5': _safe_float(last.get('ma5'), close),
                'ma20': _safe_float(last.get('ma20'), close),
                'ma60': _safe_float(last.get('ma60'), close),
                'rsi_14': _safe_float(last.get('rsi_14'), 50.0),
                'macd': _safe_float(last.get('macd'), 0.0),
                'macd_signal': _safe_float(last.get('macd_signal'), 0.0),
                'macd_hist': _safe_float(last.get('macd_hist'), 0.0),
                'volume_ratio': round(v_ratio, 4),
                'five_day_return': _safe_float(last.get('ret5'), 0.0),
                'ten_day_return': _safe_float(last.get('ret10'), 0.0),
                'mfi_14': _safe_float(last.get('mfi'), 50.0),
                'adx': _safe_float(last.get('adx'), 20.0),
            }
        except Exception:
            # Hard minimal fallback - still produces valid StockFeatures
            latest = {
                'close': close, 'volume': volume,
                'ma5': close, 'ma20': close, 'ma60': close,
                'rsi_14': 50.0, 'macd': 0.0, 'macd_signal': 0.0, 'macd_hist': 0.0,
                'volume_ratio': 1.0, 'five_day_return': 0.0, 'ten_day_return': 0.0,
                'mfi_14': 50.0, 'adx': 20.0,
            }

    # === Populate fields from latest (indicators or fallback) ===
    ma5 = _safe_float(latest.get('ma5'), close)
    ma20 = _safe_float(latest.get('ma20'), close)
    ma60 = _safe_float(latest.get('ma60'), close)
    rsi_14 = _safe_float(latest.get('rsi_14'), 50.0)
    macd = _safe_float(latest.get('macd'), 0.0)
    macd_signal = _safe_float(latest.get('macd_signal'), 0.0)
    macd_hist = _safe_float(latest.get('macd_hist'), 0.0)
    volume_ratio = _safe_float(latest.get('volume_ratio'), 1.0)
    five_day_return = _safe_float(latest.get('five_day_return'), 0.0)
    ten_day_return = _safe_float(latest.get('ten_day_return'), 0.0)
    mfi_14 = _safe_float(latest.get('mfi_14', latest.get('mfi')), 50.0)
    adx = _safe_float(latest.get('adx'), 20.0)

    above_ma5 = close > ma5
    above_ma20 = close > ma20
    above_ma60 = close > ma60

    # Base trend
    trend_strength = 0.0
    if above_ma5: trend_strength += 0.22
    if above_ma20: trend_strength += 0.22
    if above_ma60: trend_strength += 0.28

    mom = max(min((five_day_return * 0.65 + ten_day_return * 0.35) / 28.0, 0.6), -0.6)
    trend_strength += mom

    # ADX extra: amplifies trend direction strength
    adx_w = min(max((adx - 12) / 40.0, 0.0), 0.75)
    trend_strength += adx_w * (0.12 if trend_strength >= 0 else -0.08)
    trend_strength = max(min(trend_strength, 1.0), -1.0)

    volume_spike = volume_ratio > 2.0
    volume_explosion = volume_ratio > 3.0

    # ========== EXTRA: Simple MACD Divergence Detection ==========
    # 7-bar lookback. Adjusts trend_strength. (No new fields stored.)
    macd_div = 0
    try:
        if len(df) >= 7:
            macd_temp = ta.macd(df['close'], fast=12, slow=26, signal=9)
            if macd_temp is not None and len(macd_temp) >= 7:
                hist_s = macd_temp.iloc[:, 1]
                p0, p1 = df['close'].iloc[-7], df['close'].iloc[-1]
                h0, h1 = hist_s.iloc[-7], hist_s.iloc[-1]
                if p0 != 0:
                    pch = (p1 - p0) / p0
                    hch = h1 - h0
                    if pch > 0.012 and hch < -0.025:   # bearish divergence
                        macd_div = -1
                        trend_strength = max(-1.0, trend_strength - 0.18)
                    elif pch < -0.012 and hch > 0.025:  # bullish divergence
                        macd_div = 1
                        trend_strength = min(1.0, trend_strength + 0.18)
    except Exception:
        pass

    # ========== EXTRA: MFI integration ==========
    if mfi_14 > 78 and volume_spike:
        trend_strength = max(-1.0, trend_strength - 0.07)  # exhaustion risk
    elif mfi_14 < 22 and volume_spike:
        trend_strength = min(1.0, trend_strength + 0.07)   # potential bottom + vol

    trend_strength = round(max(min(trend_strength, 1.0), -1.0), 3)

    # ========== Supply (investor) ==========
    foreign_netbuy = 0
    inst_netbuy = 0
    netbuy_score = 0.0
    if investor_data and isinstance(investor_data, (dict, pd.Series)):
        f_raw = investor_data.get('foreign_netbuy', investor_data.get('foreign', investor_data.get('외국인', 0)))
        i_raw = investor_data.get('inst_netbuy', investor_data.get('institution', investor_data.get('기관합계', investor_data.get('기관', 0))))
        foreign_netbuy = safe_int(f_raw, 0)
        inst_netbuy = safe_int(i_raw, 0)

    net_total = foreign_netbuy + inst_netbuy
    if net_total != 0:
        netbuy_score = max(-5.0, min(5.0, net_total / 2_000_000_000.0))
    # small coupling of supply into trend
    trend_strength = round(max(min(trend_strength + netbuy_score * 0.035, 1.0), -1.0), 3)

    # Final StockFeatures (surge_score/reason etc remain defaults for predictor)
    return StockFeatures(
        ticker=str(ticker),
        name=str(name) if name else str(ticker),
        target_date=str(target_date),
        close=round(close, 2),
        volume=volume,
        volume_ratio=round(volume_ratio, 3),
        ma5=round(ma5, 2),
        ma20=round(ma20, 2),
        ma60=round(ma60, 2),
        rsi_14=round(rsi_14, 2),
        macd=round(macd, 4),
        macd_signal=round(macd_signal, 4),
        macd_hist=round(macd_hist, 4),
        five_day_return=round(five_day_return, 2),
        ten_day_return=round(ten_day_return, 2),
        above_ma5=bool(above_ma5),
        above_ma20=bool(above_ma20),
        above_ma60=bool(above_ma60),
        trend_strength=trend_strength,
        volume_spike=bool(volume_spike),
        volume_explosion=bool(volume_explosion),
        foreign_netbuy=foreign_netbuy,
        inst_netbuy=inst_netbuy,
        netbuy_score=round(netbuy_score, 2),
        rank=int(rank) if rank is not None else 0,
    )


def batch_analyze(tickers_info: List[dict], ohlcv_dict: dict, investor_dict: dict,
                  target_date: str, enrich_supply: bool = True) -> List[StockFeatures]:
    """
    여러 종목 일괄 처리 (v1 + v2 지원)

    - ohlcv_dict: 티커별 OHLCV DataFrame
    - investor_dict: (선택) 기본 1일 수급 데이터 (하위 호환용)
    - enrich_supply=True (기본): v2 수급 데이터(3일 누적 + 연속 방향성)를 자동 보강
      → data/fetcher의 enrich_with_investor_and_supply_data 사용

    IMPORTANT: 30종목 전체 처리를 보장. 외부에서 investor_dict를 비워두고 호출해도
    내부에서 수급 데이터를 채워줍니다.
    """
    if not tickers_info:
        return []

    results: List[StockFeatures] = []
    for idx, info in enumerate(tickers_info):
        if not isinstance(info, dict):
            continue
        ticker = info.get('ticker') or info.get('code') or info.get('종목코드') or f"TMP{idx}"
        name = info.get('name') or info.get('종목명') or str(ticker)
        rank = info.get('rank') or info.get('순위') or (idx + 1)
        ohlcv_df = ohlcv_dict.get(ticker) if isinstance(ohlcv_dict, dict) else None
        investor_data: dict = {}
        if isinstance(investor_dict, dict):
            investor_data = investor_dict.get(ticker) or investor_dict.get(str(ticker), {})

        try:
            feat = analyze_single_stock(str(ticker), str(name), ohlcv_df, investor_data, str(target_date), int(rank))
            results.append(feat)
        except Exception:
            results.append(_create_default_stock_features(ticker, name, target_date, rank))

    # v2: 3일 누적 수급 + 연속 방향성 자동 보강
    if enrich_supply and _HAS_SUPPLY_ENRICH and results:
        try:
            results = enrich_with_investor_and_supply_data(results, target_date, supply_days=3)
        except Exception as e:
            print(f"[analyzer] supply enrichment 실패 (계속 진행): {e}")

    return results

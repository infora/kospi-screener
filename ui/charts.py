"""
Subagent 5 전용
Plotly 차트 팩토리 - 4행 고품질 금융 차트
Price + MA / Volume / RSI / MACD
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime


def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼 정규화 + 날짜 인덱스 처리"""
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()
    # 컬럼명 소문자 통일
    d.columns = [str(c).lower() for c in d.columns]

    # 날짜 컬럼 처리
    if "date" in d.columns:
        d["date"] = pd.to_datetime(d["date"])
        d = d.set_index("date")
    elif not isinstance(d.index, pd.DatetimeIndex):
        try:
            d.index = pd.to_datetime(d.index)
        except Exception:
            pass

    # 필수 컬럼 보장
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in d.columns:
            if col == "volume":
                d[col] = 1_000_000
            else:
                d[col] = d.get("close", 50000)

    # OHLC 논리 보정 (합성 데이터나 잘못된 데이터 방지)
    d["high"] = d[["open", "high", "low", "close"]].max(axis=1)
    d["low"]  = d[["open", "high", "low", "close"]].min(axis=1)

    d = d.dropna(subset=["close"])
    if len(d) > 180:
        d = d.tail(180)
    return d


def _compute_indicators(df: pd.DataFrame) -> dict:
    """MA, RSI, MACD 계산 (pandas_ta 우선, 없으면 순수 pandas)"""
    ind = {}
    if df.empty:
        return ind

    close = df["close"].astype(float)
    high = df.get("high", close)
    low = df.get("low", close)
    vol = df.get("volume", pd.Series([0]*len(df)))

    # 이동평균
    ind["ma5"] = close.rolling(5, min_periods=1).mean()
    ind["ma20"] = close.rolling(20, min_periods=1).mean()
    ind["ma60"] = close.rolling(60, min_periods=1).mean()

    # RSI (14) - 순수 pandas
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14, min_periods=1).mean()
    avg_loss = loss.rolling(14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    ind["rsi"] = 100 - (100 / (1 + rs))
    ind["rsi"] = ind["rsi"].fillna(50)

    # MACD (12,26,9) - 순수 pandas
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    ind["macd"] = ema12 - ema26
    ind["macd_signal"] = ind["macd"].ewm(span=9, adjust=False).mean()
    ind["macd_hist"] = ind["macd"] - ind["macd_signal"]

    # Volume MA
    ind["vol_ma20"] = vol.rolling(20, min_periods=1).mean()

    return ind


def create_price_chart(ohlcv_df: pd.DataFrame, indicators: dict, ticker: str, name: str):
    """
    아름다운 4행 Plotly 금융 차트 반환
    행1: 캔들스틱 + MA5/20/60 (한글 제목)
    행2: 거래량 (색상 구분)
    행3: RSI + 기준선
    행4: MACD + Signal + Histogram
    """
    df = _prepare_ohlcv(ohlcv_df)
    if df.empty or len(df) < 5:
        fig = go.Figure()
        fig.add_annotation(text="차트 데이터가 부족합니다.", x=0.5, y=0.5, showarrow=False, font=dict(size=16))
        fig.update_layout(title=f"{name} ({ticker})", height=520)
        return fig

    # 지표 계산 (indicators가 부족하면 자동 보완)
    ind = _compute_indicators(df)
    if indicators:
        ind.update({k: pd.Series(v) if not isinstance(v, pd.Series) else v for k, v in indicators.items()})

    # x축 (날짜)
    x = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df.index)

    # 서브플롯 생성 (4행)
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.028,
        row_heights=[0.48, 0.14, 0.15, 0.23],
        subplot_titles=[
            "주가 및 이동평균선 (MA5·MA20·MA60)",
            "거래량",
            "RSI (14)",
            "MACD (12, 26, 9)"
        ]
    )

    # ===== Row 1: Price + MAs (캔들) =====
    # 캔들스틱
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="종가",
            increasing_line_color="#00C853",
            decreasing_line_color="#FF1744",
            increasing_fillcolor="rgba(0,200,83,0.6)",
            decreasing_fillcolor="rgba(255,23,68,0.6)",
            showlegend=False
        ),
        row=1, col=1
    )

    # 이동평균선
    colors_ma = {"ma5": "#FF9800", "ma20": "#2196F3", "ma60": "#9C27B0"}
    labels_ma = {"ma5": "MA5", "ma20": "MA20", "ma60": "MA60"}
    for key in ["ma5", "ma20", "ma60"]:
        if key in ind and len(ind[key]) == len(df):
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=ind[key],
                    name=labels_ma[key],
                    line=dict(color=colors_ma[key], width=1.8),
                    hovertemplate=f"{labels_ma[key]}: %{{y:,.0f}}<extra></extra>"
                ),
                row=1, col=1
            )

    # ===== Row 2: Volume =====
    # 상승/하락에 따른 색상
    colors_vol = []
    for i in range(len(df)):
        if i == 0 or df["close"].iloc[i] >= df["close"].iloc[i-1]:
            colors_vol.append("#00C853")
        else:
            colors_vol.append("#FF1744")

    fig.add_trace(
        go.Bar(
            x=x,
            y=df["volume"],
            name="거래량",
            marker_color=colors_vol,
            opacity=0.82,
            hovertemplate="거래량: %{y:,.0f}<extra></extra>"
        ),
        row=2, col=1
    )
    # Volume MA20
    if "vol_ma20" in ind and len(ind["vol_ma20"]) == len(df):
        fig.add_trace(
            go.Scatter(
                x=x,
                y=ind["vol_ma20"],
                name="거래량 MA20",
                line=dict(color="#FF6F00", width=1.6, dash="dot"),
                hovertemplate="Vol MA20: %{y:,.0f}<extra></extra>"
            ),
            row=2, col=1
        )

    # ===== Row 3: RSI =====
    rsi_vals = ind.get("rsi", pd.Series([50]*len(df)))
    fig.add_trace(
        go.Scatter(
            x=x,
            y=rsi_vals,
            name="RSI",
            line=dict(color="#7B1FA2", width=2.0),
            hovertemplate="RSI: %{y:.1f}<extra></extra>"
        ),
        row=3, col=1
    )
    # 기준선
    for level, color, dash in [(30, "#FF9800", "dash"), (50, "#9E9E9E", "dot"), (70, "#FF9800", "dash")]:
        fig.add_hline(
            y=level,
            line=dict(color=color, width=1.0, dash=dash),
            row=3, col=1
        )
    fig.update_yaxes(range=[0, 100], row=3, col=1)

    # ===== Row 4: MACD =====
    macd = ind.get("macd", pd.Series([0]*len(df)))
    signal = ind.get("macd_signal", pd.Series([0]*len(df)))
    hist = ind.get("macd_hist", pd.Series([0]*len(df)))

    fig.add_trace(
        go.Scatter(
            x=x,
            y=macd,
            name="MACD",
            line=dict(color="#1565C0", width=1.8),
            hovertemplate="MACD: %{y:.2f}<extra></extra>"
        ),
        row=4, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=signal,
            name="Signal",
            line=dict(color="#E65100", width=1.8),
            hovertemplate="Signal: %{y:.2f}<extra></extra>"
        ),
        row=4, col=1
    )

    # Histogram (색상 구분)
    hist_colors = ["#00C853" if h >= 0 else "#FF1744" for h in hist]
    fig.add_trace(
        go.Bar(
            x=x,
            y=hist,
            name="Histogram",
            marker_color=hist_colors,
            opacity=0.75,
            hovertemplate="Hist: %{y:.2f}<extra></extra>"
        ),
        row=4, col=1
    )

    # ===== 레이아웃 & 스타일 =====
    fig.update_layout(
        title=dict(
            text=f"<b>{name}</b> ({ticker}) — 상세 기술적 분석 차트",
            x=0.02,
            font=dict(size=18, color="#1A237E")
        ),
        height=680,
        margin=dict(l=50, r=30, t=60, b=30),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0.01,
            font=dict(size=11),
            bgcolor="rgba(255,255,255,0.85)"
        ),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="white",
        font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif", size=11)
    )

    # X축 포맷 (날짜)
    fig.update_xaxes(
        showgrid=True,
        gridcolor="#E0E0E0",
        tickformat="%m/%d",
        rangeslider_visible=False,
        row=4, col=1
    )

    # Y축 스타일
    fig.update_yaxes(title_text="가격 (원)", row=1, col=1, showgrid=True, gridcolor="#E8E8E8")
    fig.update_yaxes(title_text="거래량", row=2, col=1, showgrid=True, gridcolor="#E8E8E8")
    fig.update_yaxes(title_text="RSI", row=3, col=1, showgrid=True, gridcolor="#E8E8E8")
    fig.update_yaxes(title_text="MACD", row=4, col=1, showgrid=True, gridcolor="#E8E8E8")

    # 서브플롯 타이틀 스타일
    for ann in fig.layout.annotations:
        if ann.text:
            ann.font = dict(size=12, color="#37474F", family="Malgun Gothic")

    return fig

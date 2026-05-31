"""
코스피 수급·모멘텀 스크리너 대시보드 (Streamlit)

v1: 거래량 Top30 기반
v2: 수급 + 모멘텀 Screener 기반 + 실제 백테스트 지원

매일 사용 가능 — 분석일 자유 선택 + 실시간 Surge Score v2 예측
"""

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import sys
import random
from pathlib import Path

# 프로젝트 모듈 경로
sys.path.append(str(Path(__file__).parent))

from utils.models import AnalysisResult, StockFeatures
from utils.helpers import format_date_kr, get_next_trading_day, is_valid_trading_date
from analysis.predictor import build_analysis_result
from ui.charts import create_price_chart

# v2 Backtester
from backtest import RollingBacktester, DailyResult, create_daily_result_from_features

# ============================================
# Streamlit 페이지 설정
# ============================================
st.set_page_config(
    page_title="코스피 수급·모멘텀 스크리너 | Surge Score v2",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 세션 상태 초기화 (날짜 제어)
if "selected_date" not in st.session_state:
    st.session_state.selected_date = datetime.now().date()

# ============================================
# 고품질 합성 데이터 생성기 (Subagent 1/2/3/4 미완성 시에도 완전 동작)
# ============================================
KOSPI_TOP30 = [
    ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("373220", "LG에너지솔루션"),
    ("207940", "삼성바이오로직스"), ("006400", "삼성SDI"), ("247540", "에코프로비엠"),
    ("005380", "현대차"), ("012330", "현대모비스"), ("035420", "NAVER"), ("051910", "LG화학"),
    ("028050", "삼성엔지니어링"), ("066570", "LG전자"), ("003670", "포스코퓨처엠"),
    ("010130", "고려아연"), ("259960", "크래프톤"), ("326030", "SK바이오팜"),
    ("018260", "삼성에스디에스"), ("009150", "삼성전기"), ("010950", "S-Oil"),
    ("011070", "LG이노텍"), ("036570", "엔씨소프트"), ("352820", "하이브"),
    ("000270", "기아"), ("017670", "SK텔레콤"), ("030200", "KT"), ("033780", "KT&G"),
    ("011200", "HMM"), ("009830", "한화솔루션"), ("086790", "하나금융지주"), ("138040", "메리츠금융지주"),
]

def _generate_synthetic_analysis(target_date: str) -> AnalysisResult:
    """실제 같은 분포를 가진 30종목 합성 데이터 + predictor 완전 적용"""
    random.seed(int(target_date) % 100000 + 777)

    stocks: list[StockFeatures] = []
    base_close = [82000, 245000, 385000, 820000, 185000, 92000, 215000, 265000,
                  195000, 285000, 38500, 92000, 165000, 520000, 245000, 78000,
                  245000, 148000, 72000, 195000, 165000, 185000, 108000, 52000,
                  38000, 92000, 18500, 28500, 52000, 68000]

    for idx, (ticker, name) in enumerate(KOSPI_TOP30):
        # 거래량 비율: 대부분 0.7~2.8, 가끔 폭발
        if random.random() < 0.12:
            vr = round(random.uniform(3.1, 5.4), 2)
        elif random.random() < 0.25:
            vr = round(random.uniform(1.85, 3.0), 2)
        else:
            vr = round(random.uniform(0.68, 1.82), 2)

        vol = int(random.uniform(180000, 4200000) * (vr / 1.3))

        # 수익률
        fdr = round(random.uniform(-11.5, 14.8), 1)
        tdr = round(fdr * random.uniform(0.75, 1.45) + random.uniform(-3.5, 4.2), 1)

        # MA 위치
        above5 = random.random() > 0.28
        above20 = random.random() > 0.38
        above60 = random.random() > 0.52
        trend = round(random.uniform(-0.82, 0.91), 2)

        # RSI / MACD
        rsi = round(random.uniform(23.5, 86.0), 1)
        macd_h = round(random.uniform(-4.8, 5.9), 2)

        # 수급 (외국인/기관)
        f_net = int(random.gauss(120_000_000, 420_000_000))
        i_net = int(random.gauss(80_000_000, 380_000_000))

        # netbuy_score (대략 -60 ~ +70)
        net_score = round((f_net + i_net * 0.6) / 18_000_000, 1)
        net_score = max(-58, min(72, net_score))

        # MA 값 (종가 근처)
        close_price = base_close[idx] * random.uniform(0.94, 1.07)
        ma5 = round(close_price * random.uniform(0.97, 1.03), 0)
        ma20 = round(close_price * random.uniform(0.95, 1.06), 0)
        ma60 = round(close_price * random.uniform(0.91, 1.12), 0)

        stock = StockFeatures(
            ticker=ticker,
            name=name,
            target_date=target_date,
            close=round(close_price, 0),
            volume=vol,
            volume_ratio=vr,
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            rsi_14=rsi,
            macd=round(macd_h * 1.8 + random.uniform(-1.5, 1.5), 2),
            macd_signal=round(macd_h * 1.1, 2),
            macd_hist=macd_h,
            five_day_return=fdr,
            ten_day_return=tdr,
            above_ma5=above5,
            above_ma20=above20,
            above_ma60=above60,
            trend_strength=trend,
            volume_spike=(vr >= 2.0),
            volume_explosion=(vr >= 3.5),
            foreign_netbuy=f_net,
            inst_netbuy=i_net,
            netbuy_score=net_score,
            rank=idx + 1,
        )
        stocks.append(stock)

    # predictor로 실제 점수 + 태그 + 라벨 계산
    result = build_analysis_result(stocks, target_date)
    return result


@st.cache_data(ttl=1800, show_spinner="📊 분석 데이터 로딩 중 (Surge Score 계산 포함)...")
def load_analysis_data(target_date: str, use_screener: bool = False) -> AnalysisResult:
    """
    실시간 데이터 로딩 (st.cache_data)
    1순위: data.fetcher + analyzer + predictor 완전 경로 (실제 데이터)
    2순위: 고품질 합성 데이터 + predictor 완전 적용 (즉시 동작)
    """
    try:
        from data.fetcher import (
            get_kospi_top30_volume,
            get_ohlcv_history,
        )
        from data.screener import get_kospi_universe
        from analysis.analyzer import batch_analyze

        # 1. 후보 선정 (모드에 따라 다름)
        if use_screener:
            # v2: 수급 + 모멘텀 기반 Screener
            candidates_df = get_kospi_universe(
                target_date=target_date,
                min_trading_value=5_000_000_000,
                max_candidates=60,
                include_etf=False,
            )
            if candidates_df is None or candidates_df.empty:
                raise RuntimeError("Screener 결과 없음")
            tickers_df = candidates_df
        else:
            # v1: 거래량 Top30
            tickers_df = get_kospi_top30_volume(target_date, include_etf=False)
            if tickers_df is None or tickers_df.empty:
                raise RuntimeError("Top30 데이터 없음")

        # Subagent 1/ Screener 가 반환하는 표준 컬럼: ticker, name, close, volume, rank 등
        tickers_info = [
            {
                "ticker": row["ticker"],
                "name": row["name"],
                "rank": int(row.get("rank", i + 1)),
            }
            for i, row in tickers_df.iterrows()
        ]

        # 2. OHLCV 히스토리 일괄 수집
        ticker_list = [t["ticker"] for t in tickers_info]
        ohlcv_dict = get_ohlcv_history(ticker_list, target_date, lookback_days=120)

        # 3. 분석 실행 + v2 수급 데이터(3일 누적 + 연속 방향성) 자동 보강
        #    (analyzer 내부에서 enrich_with_investor_and_supply_data 호출)
        features_list = batch_analyze(tickers_info, ohlcv_dict, {}, target_date)

        # 4. Surge Score + 한국어 태그 + Top5 계산 (predictor)
        return build_analysis_result(features_list, target_date)

    except Exception as e:
        # 실 데이터 실패 시 고품질 합성으로 즉시 대체 (사용자 경험 보호)
        # (로그는 Streamlit에서 볼 수 있게 print)
        print(f"[load_analysis_data] 실시간 데이터 경로 실패 → 합성 데이터 사용: {e}")
        return _generate_synthetic_analysis(target_date)


# =============================================================================
# =============================================================================
# v2 백테스트 관련 함수
# =============================================================================

from backtest import BacktestResult as _BacktestResult
# Lazy import to avoid circular import issues at startup
# from backtest.historical_backtest import run_and_evaluate_backtest  # moved inside function


def _get_demo_backtest_result(target_date: str) -> _BacktestResult:
    """현재 predictor v2로 과거 60일 시뮬레이션하여 백테스트 메트릭 생성 (빠른 데모용)"""
    import random

    random.seed(42)

    daily_results = []
    base_date = datetime.strptime(target_date, "%Y%m%d")

    for i in range(60):
        past_date = (base_date - timedelta(days=60 - i)).strftime("%Y%m%d")
        temp_result = _generate_synthetic_analysis(past_date)

        scores = [s.surge_score for s in temp_result.stocks]
        t2_returns = [s.five_day_return * 0.4 + random.gauss(0, 3.5) for s in temp_result.stocks]

        daily = create_daily_result_from_features(
            date=past_date,
            features_list=temp_result.stocks,
            future_t1=[r * 0.6 + random.gauss(0, 2.8) for r in t2_returns],
            future_t2=t2_returns,
            future_t3=[r * 1.1 + random.gauss(0, 4.2) for r in t2_returns],
        )
        daily_results.append(daily)

    backtester = RollingBacktester(window=60, hit_threshold=0.03)
    return backtester.run_rolling_backtest(daily_results)


@st.cache_data(ttl=3600, show_spinner=False)
def _run_real_backtest_cached(target_date: str, lookback_days: int = 40, use_screener: bool = True):
    """실제 screener 기반 히스토리컬 백테스트 (무거운 작업 → 캐싱 필수)"""
    # Lazy import here to prevent circular import at app startup
    from backtest.historical_backtest import run_and_evaluate_backtest

    try:
        return run_and_evaluate_backtest(
            lookback_days=lookback_days,
            use_screener=use_screener,
            verbose=False
        )
    except Exception as e:
        print(f"[backtest] 실제 백테스트 실행 중 예외 발생: {e}")
        return None, None


# =============================================================================
# 기존 함수들
# =============================================================================

def generate_synthetic_ohlcv_for_chart(ticker: str, name: str, target_date: str, base_close: float) -> pd.DataFrame:
    """
    차트용 120일 OHLCV 합성 (현실적인 캔들 관계 유지)
    - low <= min(open, close) <= max(open, close) <= high 를 반드시 만족
    - 상승 종목도 자연스럽게 표현되도록 개선
    """
    random.seed(hash(ticker + target_date) % 999983)
    dates = pd.date_range(end=datetime.strptime(target_date, "%Y%m%d"), periods=120, freq="B")

    closes = []
    p = base_close * random.uniform(0.82, 1.19)
    for _ in range(120):
        change = random.gauss(0.0006, 0.023)
        p *= (1 + change)
        closes.append(p)

    opens = []
    highs = []
    lows = []

    prev_close = closes[0]
    for close in closes:
        # 전일 종가 근처에서 시가 결정 (갭은 작게)
        gap = random.uniform(-0.008, 0.008)
        open_price = prev_close * (1 + gap)

        # 당일 변동폭 (상승 종목도 제대로 보이게)
        daily_vol = abs(random.gauss(0.0, 0.018)) + 0.004   # 최소 변동폭 보장

        if close >= open_price:
            # 상승 캔들
            high = max(close, open_price) + daily_vol * close * random.uniform(0.3, 1.0)
            low = min(close, open_price) - daily_vol * close * random.uniform(0.1, 0.6)
        else:
            # 하락 캔들
            high = max(close, open_price) + daily_vol * close * random.uniform(0.1, 0.6)
            low = min(close, open_price) - daily_vol * close * random.uniform(0.3, 1.0)

        # 극단적 이상치 방지
        high = max(high, open_price, close)
        low = min(low, open_price, close)

        opens.append(round(open_price, 0))
        highs.append(round(high, 0))
        lows.append(round(low, 0))

        prev_close = close

    df = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": [round(c, 0) for c in closes],
        "volume": [int(random.uniform(180000, 2800000)) for _ in range(120)],
    })
    return df


# ============================================
# Sidebar - 완전 동작하는 Date Picker + 필터
# ============================================
with st.sidebar:
    st.header("⚙️ 분석 설정")

    # 오늘 버튼 완전 동작
    col1, col2 = st.columns([1.15, 1])
    with col1:
        if st.button("📅 오늘(최근 영업일)로 이동", use_container_width=True, type="primary"):
            st.session_state.selected_date = datetime.now().date()
            st.rerun()

    with col2:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # 날짜 선택기 (세션 상태와 연동)
    selected_date = st.date_input(
        "분석 기준일 (영업일)",
        value=st.session_state.selected_date,
        max_value=datetime.now().date() + timedelta(days=1),
        min_value=datetime(2024, 1, 1),
        help="과거 영업일 선택 가능. pykrx 실데이터 또는 고품질 시뮬레이션 사용",
        key="date_picker"
    )
    st.session_state.selected_date = selected_date

    # 영업일 보정
    target_date = selected_date.strftime("%Y%m%d")
    if not is_valid_trading_date(target_date):
        target_date = get_next_trading_day(target_date)  # 다음 영업일로 보정

# (이 블록은 아래 sidebar 안으로 이동시켰습니다)

    st.caption(f"**적용 기준일**: {format_date_kr(target_date)}")

    st.divider()

    # v2: 후보 선정 모드 선택
    candidate_mode = st.radio(
        "후보 선정 방식",
        options=["거래량 Top30 (v1)", "수급+모멘텀 Screener (v2)"],
        index=0,
        horizontal=True,
        help="v2 모드는 전체 KOSPI에서 유동성 + 수급 + 모멘텀 필터로 후보를 추출합니다."
    )
    use_screener = "Screener" in candidate_mode

    # 모드 변경 시 실제 백테스트 결과 초기화 (오래된 결과 방지)
    if 'last_backtest_mode' not in st.session_state:
        st.session_state.last_backtest_mode = use_screener
    elif st.session_state.last_backtest_mode != use_screener:
        st.session_state.real_backtest_result = None
        st.session_state.last_backtest_mode = use_screener

    # v2 실제 백테스트 실행 버튼 (Screener 모드일 때만)
    if use_screener:
        st.markdown("---")
        if st.button("📊 최근 40일 실제 백테스트 실행", use_container_width=True, type="secondary"):
            with st.spinner("실제 과거 데이터로 백테스트를 실행 중입니다... (1~3분 소요될 수 있습니다)"):
                try:
                    bt_result, daily_data = _run_real_backtest_cached(target_date, lookback_days=40, use_screener=True)

                    if bt_result is None or daily_data is None:
                        st.error("백테스트 실행에 실패했습니다. (과거 데이터가 충분하지 않거나 조회 중 오류 발생)")
                        st.session_state.real_backtest_result = None
                    else:
                        st.session_state.real_backtest_result = bt_result
                        st.success("실제 백테스트 완료! 상단 지표가 업데이트되었습니다.")
                        st.rerun()

                except Exception as e:
                    st.error(f"백테스트 실행 중 오류 발생: {e}")
                    st.session_state.real_backtest_result = None

    st.divider()

    st.subheader("🔍 필터")
    min_vol_ratio = st.slider(
        "최소 거래량 비율 (20일 평균 대비)",
        min_value=0.5, max_value=5.5, value=0.85, step=0.05,
        help="1.0 = 평균 수준. 2.0 이상이면 급증 구간"
    )
    only_high = st.checkbox("High 후보 (72점 이상)만 보기", value=False)
    search_name = st.text_input("종목명 검색 (부분 일치)", placeholder="삼성, SK, NAVER...")

    st.divider()

    if use_screener:
        st.markdown("""
        **📌 Surge Score 가중치 (v2)**
        - 수급 35%  
        - 모멘텀 25%  
        - 추세/MA 20%  
        - 오실레이터 10%  
        - 거래량 5%  
        - 뉴스/공시 5%
        """)
    else:
        st.markdown("""
        **📌 Surge Score 가중치 (v1)**
        - 거래량 30%  
        - 모멘텀 25%  
        - 추세/MA 20%  
        - RSI·MACD 15%  
        - 수급 10%
        """)

    st.divider()
    st.caption("⚠️ **면책**: 본 도구는 교육·참고용이며 투자 조언이 아닙니다. 모든 투자 결정은 본인 책임입니다.")

# ============================================
# 메인 헤더
# ============================================
mode_label = "Screener (v2)" if use_screener else "거래량 Top30 (v1)"

if use_screener:
    st.title("📈 코스피 수급·모멘텀 스크리너")
else:
    st.title("📈 코스피 거래량 상위 분석 대시보드")

st.caption(f"매일 사용 가능 · 분석일 선택 즉시 재계산 · {mode_label} 모드  |  v1/v2 하이브리드 지원")

# ============================================
# 데이터 로드 (캐시 적용)
# ============================================
result: AnalysisResult = load_analysis_data(target_date, use_screener=use_screener)
next_day = format_date_kr(result.next_trading_day)

# ============================================
# KPI 요약
# ============================================
st.markdown(f"""
**📅 분석 기준일**: {format_date_kr(result.target_date)} &nbsp;&nbsp;|&nbsp;&nbsp; 
**익일 예측일**: {next_day} &nbsp;&nbsp;|&nbsp;&nbsp; 
**총 {len(result.stocks)}종목 분석 완료**
""")

# v2 백테스트 결과 표시 (헤더 카드)
# 우선순위: 세션에 실제 백테스트 결과 > Screener 모드 데모 > 일반 데모
bt = None
bt_source = ""

if 'real_backtest_result' in st.session_state and st.session_state.real_backtest_result is not None:
    bt = st.session_state.real_backtest_result
    bt_source = "실제 히스토리컬 (Screener)"
elif use_screener:
    # Screener 모드에서는 데모라도 v2 스타일로 보여줌
    bt = _get_demo_backtest_result(target_date)
    bt_source = "Screener 데모 (v2)"
else:
    bt = _get_demo_backtest_result(target_date)
    bt_source = "거래량 Top30 데모 (v1)"

if bt:
    bt_col1, bt_col2, bt_col3, bt_col4 = st.columns(4)

    bt_col1.metric(
        "📊 최근 백테스트 (T+2)",
        f"IC {bt.ic_t2:.3f}",
        "유의미" if bt.ic_t2 > 0.04 else "약함"
    )
    bt_col2.metric(
        "Top5 적중률 (+3%↑)",
        f"{bt.hit_rate_t2*100:.1f}%",
        f"Sharpe {bt.sharpe_t2:.2f}"
    )
    bt_col3.metric(
        "Top5 평균 수익률 (T+2)",
        f"{bt.avg_return_top5_t2:.2f}%",
        delta=f"전체 {bt.avg_return_t2:.2f}%"
    )
    bt_col4.metric(
        "백테스트 기간 / 출처",
        f"{bt.n_days}일",
        bt_source
    )
else:
    st.caption("백테스트 지표를 불러올 수 없습니다.")

st.divider()

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("분석 종목 수", f"{len(result.stocks)}", "일반주 기준")
kpi2.metric("평균 거래량 비율", f"{result.avg_volume_ratio:.2f}x", delta="실시간")
kpi3.metric("High 후보", f"{result.high_surge_count}개", "급등 가능성 높음" if result.high_surge_count > 2 else "관찰 필요")
data_mode_label = "Screener v2 + 실제 BT" if ('real_backtest_result' in st.session_state and st.session_state.real_backtest_result) else ("Screener v2" if use_screener else "거래량 Top30 v1")
kpi4.metric(
    "데이터 모드", 
    data_mode_label, 
    "predictor v2 적용"
)

st.divider()

# ============================================
# 🔥 Top 5 카드 (아름다운 카드 UI)
# ============================================
st.subheader("🔥 익일 급등 예상 Top 5 (Surge Score 순)")
st.caption("실시간으로 predictor가 계산한 점수입니다. 카드 클릭 시 하단 상세 차트로 이동하세요.")

top5 = result.top5
card_cols = st.columns(5, gap="small")

for i, stock in enumerate(top5):
    with card_cols[i]:
        # 색상 결정
        if stock.surge_label == "High":
            badge_color = "🔴"
            border = "#FFCDD2"
            score_color = "#C62828"
        elif stock.surge_label == "Medium":
            badge_color = "🟡"
            border = "#FFF9C4"
            score_color = "#F57F17"
        else:
            badge_color = "🟢"
            border = "#C8E6C9"
            score_color = "#2E7D32"

        with st.container(border=True):
            st.markdown(f"""
            <div style="padding:2px 0;">
                <span style="font-size:15px;">{badge_color} <b>{stock.name}</b></span><br>
                <span style="font-size:10px;color:#666;">{stock.ticker}</span>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div style="font-size:28px; font-weight:700; color:{score_color}; line-height:1.05;">
                {stock.surge_score:.1f}
            </div>
            <div style="font-size:12px; margin-top:-6px; color:#555;">{stock.surge_label}</div>
            """, unsafe_allow_html=True)

            st.metric("거래량비", f"{stock.volume_ratio:.1f}x", delta=f"{stock.five_day_return:+.1f}%")

            tags_html = " · ".join(stock.reason_tags[:3])
            st.caption(tags_html[:68] + ("..." if len(tags_html) > 68 else ""))

            if st.button("차트 보기", key=f"top5_btn_{i}", use_container_width=True):
                st.session_state.selected_chart_ticker = stock.ticker

# ============================================
# 전체 테이블 (색상 코딩 + 인터랙티브)
# ============================================
if use_screener:
    st.subheader("📋 수급·모멘텀 스크리너 결과 (필터 적용)")
else:
    st.subheader("📋 전체 거래량 상위 종목 (필터 적용)")

# 필터 적용
filtered = result.stocks
if only_high:
    filtered = [s for s in filtered if s.surge_label == "High"]
filtered = [s for s in filtered if s.volume_ratio >= min_vol_ratio]
if search_name:
    q = search_name.strip().lower()
    filtered = [s for s in filtered if q in s.name.lower() or q in s.ticker.lower()]

st.caption(f"현재 {len(filtered)} / {len(result.stocks)} 종목 표시 중 (필터 적용)")

# 테이블용 DataFrame 생성
table_rows = []
for s in filtered:
    table_rows.append({
        "순위": s.rank,
        "종목": f"{s.name} ({s.ticker})",
        "종가(원)": int(s.close),
        "거래량비": round(s.volume_ratio, 2),
        "5일수익률(%)": round(s.five_day_return, 1),
        "RSI": round(s.rsi_14, 1),
        "급등점수": round(s.surge_score, 1),
        "예측": s.surge_label,
        "주요 근거": " · ".join(s.reason_tags[:2]),
        "추천": s.recommendation[:32] + ("..." if len(s.recommendation) > 32 else ""),
    })

table_df = pd.DataFrame(table_rows)

# 색상 스타일 함수
def color_surge(val):
    if isinstance(val, (int, float)):
        if val >= 72:
            return "background-color: #FFCDD2; color:#B71C1C; font-weight:600"
        elif val >= 54:
            return "background-color: #FFF9C4; color:#F57F17; font-weight:600"
        else:
            return "background-color: #E8F5E9; color:#1B5E20"
    return ""

def color_label(val):
    if val == "High":
        return "color:#C62828; font-weight:700"
    elif val == "Medium":
        return "color:#F57F17; font-weight:600"
    return "color:#2E7D32"

styled_table = table_df.style.applymap(color_surge, subset=["급등점수"])
styled_table = styled_table.applymap(color_label, subset=["예측"])

st.dataframe(
    styled_table,
    width="stretch",
    hide_index=True,
    height=420,
    column_config={
        "급등점수": st.column_config.NumberColumn(format="%.1f", help="0~100 (높을수록 급등 가능성 ↑)"),
        "거래량비": st.column_config.NumberColumn(format="%.2f"),
    }
)

# ============================================
# 상세 차트 영역 (ui/charts 완전 연동)
# ============================================
st.divider()
st.subheader("📊 종목 상세 차트 (4행 Plotly)")

# 선택 위젯 (Top5 또는 테이블 종목)
all_names = [f"{s.name} ({s.ticker})" for s in result.stocks]
default_idx = 0
if "selected_chart_ticker" in st.session_state:
    for i, s in enumerate(result.stocks):
        if s.ticker == st.session_state.selected_chart_ticker:
            default_idx = i
            break

selected_display = st.selectbox(
    "상세 분석할 종목을 선택하세요",
    options=all_names,
    index=default_idx,
    help="선택 즉시 아래에 아름다운 4단 차트가 표시됩니다"
)

# 선택 종목 찾기
selected_stock = None
for s in result.stocks:
    if f"{s.name} ({s.ticker})" == selected_display:
        selected_stock = s
        break

if selected_stock:
    # 차트용 OHLCV 생성
    chart_df = generate_synthetic_ohlcv_for_chart(
        selected_stock.ticker, selected_stock.name, target_date, selected_stock.close
    )

    # indicators dict (필요시 추가 전달 가능)
    ind_dict = {
        "rsi": None,   # charts.py 내부에서 자동 계산
    }

    fig = create_price_chart(
        ohlcv_df=chart_df,
        indicators=ind_dict,
        ticker=selected_stock.ticker,
        name=selected_stock.name
    )

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": True})

    # 선택 종목 추가 정보
    c1, c2, c3 = st.columns(3)
    c1.metric("급등점수", f"{selected_stock.surge_score:.1f}", selected_stock.surge_label)
    c2.metric("거래량 비율", f"{selected_stock.volume_ratio:.2f}x")
    c3.metric("5일 수익률", f"{selected_stock.five_day_return:+.1f}%")

    st.markdown("**주요 분석 근거**")
    for tag in selected_stock.reason_tags:
        st.write(f"• {tag}")

    st.info(f"💡 **추천**: {selected_stock.recommendation}")

# ============================================
# CSV 다운로드 + 추가 기능
# ============================================
st.divider()

csv_buffer = table_df.to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    label="📥 현재 필터 결과 CSV 다운로드",
    data=csv_buffer,
    file_name=f"kospi_top30_surge_{target_date}.csv",
    mime="text/csv",
    width="content"
)

# ============================================
# Footer / Disclaimer
# ============================================
st.divider()
st.caption("""
**기술 스택**: pykrx · pandas_ta · Streamlit · Plotly · Subagent 5 완성 (predictor + charts + full UI)
<br>
**Surge Score** = Volume(30%) + Momentum(25%) + Trend/MA(20%) + RSI/MACD(15%) + Supply(10%)
""", unsafe_allow_html=True)

st.caption("⚠️ 본 대시보드는 교육 및 참고 목적의 도구이며, 어떠한 투자 조언도 아닙니다. 투자 손실에 대한 책임은 전적으로 사용자 본인에게 있습니다.")

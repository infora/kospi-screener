# 📈 코스피 수급·모멘텀 스크리너

**실전형 코스피 급등 후보 탐색 도구 (v1 + v2 하이브리드)**

이 앱은 기존의 단순한 거래량 상위 스캐너를 넘어, **외국인/기관 수급 + 기술적 모멘텀**을 종합적으로 분석하여 더 질 높은 급등 후보를 찾아줍니다.

- **v1 모드**: 기존 거래량 Top30 기반 (레거시)
- **v2 모드**: 수급 + 모멘텀 기반 동적 Screener (추천)
- **실제 백테스트 지원**: 최근 기간의 실제 성과 지표(IC, 적중률, Sharpe) 확인 가능
- **다기간 예측**: T+1 / T+2 / T+3 신뢰도 분리 표시

> 한국 시장 특성을 반영한 실전형 분석 도구입니다.

## 주요 기능

| 기능 | v1 모드 | v2 모드 (추천) |
|------|---------|----------------|
| 후보 선정 | 거래량 상위 30종목 고정 | 유동성 + 수급 + 모멘텀 복합 필터로 동적 추출 |
| Surge Score 가중치 | 거래량 30% 중심 | 수급 35% 중심 |
| 백테스트 | - | 실제 과거 데이터 기반 IC / 적중률 / Sharpe |
| 다기간 신뢰도 | - | T+1 / T+2 / T+3 분리 표시 |

## 빠른 시작

```bash
git clone https://github.com/infora/kospi-screener.git
cd kospi-screener
pip install -r requirements.txt
streamlit run app.py
```

사이드바에서 **"후보 선정 방식"**을 선택하여 v1 / v2 모드를 전환할 수 있습니다.

## Streamlit Cloud 배포

1. GitHub에 이 저장소를 push
2. [share.streamlit.io](https://share.streamlit.io)에서 배포
3. Main file: `app.py`
4. Python version: 3.12

## 기술 스택

- Python 3.12 + Streamlit + Plotly
- pykrx (주요 데이터 소스)
- pandas_ta + scipy (지표 및 백테스트)
- yfinance (fallback)

## 주의사항

- 이 도구는 **투자 조언이 아닙니다**. 모든 투자 결정은 본인 책임입니다.
- pykrx는 외부 데이터에 의존하므로 실제 운영 시 안정성에 유의하세요.
- 백테스트 결과는 과거 데이터이며 미래를 보장하지 않습니다.

---

*Parallel Subagent Workflow로 개발된 프로젝트*
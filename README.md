# 📈 코스피 수급·모멘턴 스크리너

**수급 + 모멘턴 기반의 실전형 코스피 갑등 후보 탐색 도구**

이 앱은 기존의 단순한 거래량 상위 종목 스캐너를 넘어, **외국인/기관 수급 + 기술적 모멘턴**을 종합적으로 분석하여 더 질 높은 갑등 후보를 찾아줍니다.

- **v1 모드**: 기존 거래량 Top30 기반 (레거시)
- **v2 모드**: 수급 + 모멘턴 기반 동적 Screener (추천)
- **실제 백테스트**: 최근 기간 동안의 실제 성과(IC, 적중률, Sharpe) 확인 가능
- **다기간 예축**: T+1 / T+2 / T+3 신뢰도 분리 표시

> 한국 시장의 특성을 반영한 실전형 분석 도구입니다.

## 🚀 기능 개요

| 기능 | 설명 |
|------|------|
| 후보 선정 방식 | 거래량 Top30 (v1) / 수급+모멘턴 Screener (v2) 토글 지원 |
| Surge Score | v2 가중치 적용 (수급 35% 중심) |
| 다기간 신뢰도 | T+1 / T+2 / T+3 별도 계산 |
| 실제 백테스트 | 최근 40~60일 간 실제 성과 지표 (IC, 적중률, Sharpe) 확인 가능 |
| 데이터 | pykrx 주 사용 + yfinance 대체 |

## 👨‍💻 로컬 실행

```bash
git clone https://github.com/infora/kospi-screener.git
cd kospi-screener
pip install -r requirements.txt
streamlit run app.py
```

사이드바에서 **"후보 선정 방식"** 라디오 버튼으로 v1 / v2 모드를 자유롭게 전환할 수 있습니다.

## 🚀 GitHub + Streamlit Cloud 배포 가이드

### 1. GitHub 저장소 준비

```bash
git clone https://github.com/infora/kospi-screener.git
cd kospi-screener
```

### 2. Streamlit Cloud에 배포하기

1. [https://share.streamlit.io](https://share.streamlit.io) 접속 후 GitHub 로그인
2. **Deploy an app** 클릭
3. Repository: `infora/kospi-screener` 선택
4. Branch: `main`
5. Main file path: `app.py`
6. **Deploy!** 클릭

배포 후 앱 주소: `https://your-app-name.streamlit.app`

## ⚙️ 기술 스택

- Python 3.12
- Streamlit + Plotly
- pykrx (수급 데이터)
- pandas_ta, scipy (IC 계산)

## ⚠️ 주의사항

- 이 도구는 **투자 조언이 아닙니다**. 모든 결정은 자신의 책임 하에 있습니다.
- pykrx 데이터는 외부 스크래핑에 의존하므로, 실제 운영 시 안정성 문제가 발생할 수 있습니다.
- 백테스트 결과는 과거 성과이며, 미래 성과를 보장하지 않습니다.

---

*Parallel Subagent Workflow로 개발된 프로젝트*
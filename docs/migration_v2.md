# KOSPI Dashboard v1 → v2 마이그레이션 가이드

**프로젝트**: danta (코스피 거래량 상위 30종목 분석 앱)  
**기준일**: 2026-05-29  
**목표**: plan_v2.md 기반 정확도 중심 재설계

---

## v1 vs v2 핵심 차이점

| 영역              | v1 (현재)                     | v2 (목표)                              | 우선순위 |
|-------------------|-------------------------------|----------------------------------------|----------|
| 후보 선정          | 거래량 Top 30 고정            | 전체 KOSPI → 유동성+수급+모멘텀 필터   | P0      |
| SurgeScore 가중치  | Volume 30% / Supply 10%       | Supply 35% / Volume 5%                 | P0      |
| 예측 기간          | T+1 중심                      | T+1 / T+2 / T+3 분리 (T+2 중심)        | P1      |
| 검증 체계          | 없음                          | 백테스트 필수 (IC, Hit Rate, Sharpe)   | P0      |
| 추가 데이터        | 기본 수급                     | 3일 누적 수급 + 공매도 + 뉴스/공시     | P1~P2   |

---

## 우선순위 TODO (실행 계획)

### Phase 0: 기반 준비 (즉시 착수 추천)

- [ ] `config/settings.py` 생성 (가중치, 필터, 키워드 사전 중앙 관리)
- [ ] `utils/models.py` → `StockFeatures` v2 확장
  - `foreign_netbuy_3d`, `foreign_consecutive_days`
  - `inst_netbuy_3d`, `inst_consecutive_days`
  - `short_balance_ratio`, `short_balance_change`
  - `news_sentiment_score`, `dart_disclosure_flag`
  - `confidence_t1`, `confidence_t2`, `confidence_t3`

### Phase 1: 핵심 철학 변경 (가장 중요)

- [ ] `data/fetcher.py` 수급 데이터 강화
  - 3일 누적 순매수 계산
  - 연속 순매수/매도 일수 계산
- [ ] `analysis/predictor.py` SurgeScore v2 구현
  - Supply 35%, Volume 5%로 재설계
  - T+1/T+2/T+3 신뢰도 분리 계산
- [ ] `data/screener.py` 신규 개발 (후보 풀 변경의 핵심)
  - 전체 KOSPI 유동성 필터 (거래대금 기준)
  - 수급 1차 필터
  - 모멘텀 1차 필터
- [ ] 후보 선정 로직을 screener 기반으로 전환 (`app.py`)

### Phase 2: 예측력 강화

- [ ] `analysis/supply_demand.py` 분리 (선택)
- [ ] `analysis/short_analysis.py` 신규 (공매도 분석)
- [ ] `data/news_fetcher.py` + `analysis/sentiment.py` (경량 키워드 방식)

### Phase 3: 검증 체계 구축 (가장 가치 높은 작업)

- [ ] `backtest/backtester.py` 최소 구현
  - Rolling 60일 IC (Spearman)
  - Top5 적중률 (T+2 기준)
  - Sharpe 계산
- [ ] 백테스트 결과를 대시보드 상단에 상시 표시
- [ ] 백테스트 기반 가중치 튜닝 가이드 문서화

---

## 추천 실행 순서 (실제 작업 추천)

**1차 스프린트 (빠른 성과 + 기반 마련)**
1. `config/settings.py` 생성
2. `StockFeatures` v2 필드 추가
3. 수급 3일 누적 + 연속 방향성 데이터 추가
4. SurgeScore 가중치 v2 적용 (기존 함수 유지 + v2 함수 병행)

**2차 스프린트**
5. `screener.py` 기본 버전 개발
6. 후보 선정 로직 교체
7. T+1/T+2/T+3 신뢰도 UI 반영

**3차 스프린트 (핵심 가치)**
8. 백테스트 모듈 최소 버전
9. 대시보드에 백테스트 지표 노출

---

## 주의사항

- v2는 **후보 선정 철학 자체를 바꾸는** 작업입니다. 단순 가중치 조정만으로는 의미가 제한적입니다.
- 백테스트가 완성되기 전까지는 새로운 가중치를 과신하지 마세요.
- 초기에는 **하이브리드 방식** (거래량 Top30 + 수급 필터)로 전환하는 것도 좋은 중간 단계가 될 수 있습니다.

---

*이 문서는 `plan_v2.md`를 기반으로 현재 코드베이스에 맞춰 재구성한 실행 중심 마이그레이션 가이드입니다.*

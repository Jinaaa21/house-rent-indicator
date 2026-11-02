# 임대차 2법 시행 전후, 서울 행정동별 월세화와 전세 상승 가속은 겹쳤는가 (지표 테스트)

분석 계획은 [analysis_plan.md](analysis_plan.md)에 있습니다.

## 연구 질문

임대차 2법 시행 전후로 서울 행정동별 아파트 임차계약의 구성(전세·월세)은 어떻게 달라졌는가? 월세 비중이 서울 평균보다 크게 늘어난 동은 전세보증금 상승 속도가 시행 전보다 빨라진 동과 겹치는가? 갱신요구권이 많이 쓰인 동은 어디이며, 두 지표와 어떤 관계인가?

비교 기간: 시행 전 2018.8.~2020.7., 시행 후 2022.8.~2024.7.

## 실행 순서

각 단계는 앞 단계가 만든 파일을 읽습니다(괄호 안은 필요한 앞 단계).

```bash
pip install -r requirements.txt
cp .env.example .env          # DATA_GO_KR_KEY, VWORLD_KEY 입력 (커밋 금지)

# 1. 수집·전처리·결합
python src/01_collect.py      # 비교 기간 48개월 × 25개 구
python src/01_collect.py --ym 202008 202009 202010 202011 202012 202101 202102 202103 202104 202105 202106 202107 \
                              202108 202109 202110 202111 202112 202201 202202 202203 202204 202205 202206 202207
                              # 사이 기간 24개월(08c 진단 전용)
python src/02_clean.py        # 기간 필터, 금액·이상치·중복·공공임대 표시 (01)
python src/03_geocode.py      # 단지 주소 → 좌표 (02)
python src/04_join_admdong.py # 행정동 공간 결합, 수동 확인 반영 (02, 03)

# 2. 진단 (지표 계산 전에 확인)
python src/08_diagnostics.py         # 신고제 단절 진단, 서울 기간별 비중 (04)
python src/08b_diag_sensitivity.py   # 잠원동 제외분 영향, 결합 불일치 확인표, 기존 단지 기준 재계산 (04)
python src/08c_diag_monthly.py       # 월별 추이, 신고제 시점·위약 비교 (01, 사이 기간 포함)
python src/08d_lq_regression_check.py  # ΔLQ 평균으로의 회귀 점검 (04)

# 3. 지표
python src/05_indicator_lq.py        # 지표 A: 월세계약 LQ·ΔLQ (04)
python src/06_indicator_rg.py        # 지표 C: 상대 누적 상승률 RG (04)
python src/06b_bootstrap.py          # ΔLQ·RG 부트스트랩 90% 구간, 자치구 RG (05, 06)
python src/06c_public_rental_check.py  # g = 0 묶음, 공공임대 표시 단지 목록 (06)
python src/07_renewal.py             # 갱신요구권 사용률, 빈 값 가정 점검 (04, 06)
python src/07b_rental_candidates.py  # 이름에 키워드 없는 임대 단지 후보 (04)
python src/08e_stock_corr.py         # 주택 재고 특성과 ΔLQ·RG의 상관 (05, 06)

# 4. 공간 통계·그림·사이트
python src/09_spatial_stats.py       # 전역 Moran's I, LISA (05, 06, 07)
python src/10_figures.py             # 분석용 그림 PNG (06b, 08c, 09)
python src/11_build_site.py          # 보고서 사이트 데이터 site/data/*.json (06b, 08, 08c, 08e, 09)
```

## 자료 출처

- 아파트 전월세 실거래: 국토교통부, 공공데이터포털 '국토교통부_아파트 전월세 실거래가 자료' API
- 행정동 경계: 본 데이터는 통계청 통계지리정보서비스(SGIS, https://sgis.kostat.go.kr)에서 공공누리 제1유형으로 개방한 행정동 경계를 가공한 것이며(가공: vuski/admdongkor, https://github.com/vuski/admdongkor), CC BY 4.0으로 배포됩니다. (사용 버전: ver20261001)
- 지오코딩: 브이월드(VWorld) 지오코더 API 2.0
- 권역 구분: 「2030 생활권계획의 이해」, 서울도시공간포털

원자료(data/raw/, 약 200MB)와 중간 파일(data/interim/)은 용량이 크고 src/01_collect.py로 공공데이터포털 API에서 다시 받을 수 있어 저장소에 올리지 않았습니다.

## 보고서

보고서는 `site/`(index.html, app.js, styles.css, data/)이며 브라우저가 지도·그래프를 직접 그립니다. 로컬에서는 `cd site && python -m http.server 8000` 후 http://localhost:8000 으로 엽니다.

설정값(기간, 최소 건수, 절사 비율)은 [config.py](config.py), 자료 항목 정의는 [docs/data_fields.md](docs/data_fields.md)에 있습니다.

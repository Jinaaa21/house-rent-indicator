"""분석 설정값 (analysis_plan.md 기준). 값을 바꾸면 보고서 전처리 절에도 반영할 것."""
from pathlib import Path

# ── 경로 ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_PROCESSED = ROOT / "data" / "processed"
OUT_FIG = ROOT / "outputs" / "figures"
OUT_TAB = ROOT / "outputs" / "tables"
LOG_DIR = ROOT / "logs"

# ── 비교 기간 (analysis_plan.md 2장, 확정) ───────────────────
PERIODS = {
    "pre": ("2018-08-01", "2020-07-31"),   # 시행 전
    "post": ("2022-08-01", "2024-07-31"),  # 시행 후
}
# 비교 기간 사이 2년: 신고제 단절 진단(월별 추이)에만 쓰고 지표 계산에는 쓰지 않음
GAP_PERIOD = ("2020-08-01", "2022-07-31")
LAW_DATE = "2020-07-31"        # 임대차 2법 시행
REPORTING_DATE = "2021-06-01"  # 전월세신고제 시행

# ── 최소 건수·전처리 기준 (analysis_plan.md 3~4장, 잠정) ─────
MIN_N_LQ = 30        # 지표 A: 각 기간 행정동 계약 수
MIN_CELLS_RG = 5     # 지표 C: 행정동별 매칭 묶음 수
MIN_N_RENEW = 20     # 갱신요구권: 행정동별 갱신 계약 수
TRIM_PCT = 0.01      # ㎡당 보증금 상하위 절사 비율(기간별)
# 절사 대상: "jeonse" = 순수전세 안에서만 분위 계산·표시(지표 C용). 행은 지우지 않고 trim_out 열로 표시
#   월세 포함 계약까지 넣으면 하위 1%가 보증금이 작은 월세 계약으로 채워져 LQ의 분자·분모가 달라짐
TRIM_SCOPE = "jeonse"
AREA_ROUND = 1       # 전용면적 반올림 단위(㎡)
MIN_AREA = None      # 전용면적 극소형 제외 기준(㎡). 기본 분석은 적용하지 않음
SMALL_AREA = 20      # 민감도 점검(analysis_plan.md 5.5)용 소형 기준(㎡)

# 완전 중복 행: "keep" = 지우지 않음(기본). 동·호가 없어 서로 다른 계약인지 구별 불가
DEDUP_MODE = "keep"
DEDUP_ROBUSTNESS = True  # 중복 제거 버전으로 ΔLQ·R 재계산해 비교(analysis_plan.md 4.4)

# 기존 단지: 준공연도 ≤ 2017 (지표 A의 dLQ_exist, 진단의 기존 단지 기준)
EXIST_MAX_BUILD_YEAR = 2017
# 지표 C: 각 기간 시작 전년도까지 준공된 단지만 (입주 초기 단지의 낮은 1년차 전세가 배제)
RG_MAX_BUILD_YEAR = {"pre": 2017, "post": 2021}

# 공공임대로 보이는 단지(단지명 키워드) 제외: 임대료가 공급 기관 기준으로 정해져 시장 변화 지표에 맞지 않음
# SH·LH는 대문자이고 앞에 영문자가 없을 때만 (예: 'DasHaus' 제외). '임대'는 '(임대)', '청년임대' 등을 포함
EXCLUDE_PUBLIC_RENTAL = True
PUBLIC_RENTAL_PATTERN = (r"(?<![A-Za-z])(?:SH|LH)|에스에이치|장기전세|국민임대|행복주택|영구임대"
                         r"|휴먼시아|시프트|임대|청년주택")  # 청년주택: 역세권 청년주택, 제도상 5% 상한

# 해석 유보 행정동(adm_cd): 값은 계산하되 지도·해석에서 따로 표시
HOLD_ADMDONG = {
    "11220550": "잠원동: 좌표 실패 741건(시행 전) 배정에 따라 두 동의 ΔLQ 크기 순서가 바뀜",
    "11220590": "반포3동: 좌표 실패 741건(시행 전) 배정에 따라 두 동의 ΔLQ 크기 순서가 바뀜",
}

# 단지 키: API의 단지 일련번호. 단지명(aptNm)은 이름이 같은 서로 다른 단지가 있음
COMPLEX_KEY = "aptSeq"

# ── 수집 API (docs/data_fields.md 참고) ───────────────
API_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
API_NUM_ROWS = 1000  # 한 페이지 결과 수
API_SLEEP = 0.3      # 호출 사이 대기(초)

# ── 지오코딩·행정동 경계 ─────────────────────────────
GEOCODE_URL = "https://api.vworld.kr/req/address"  # 브이월드 지오코더 2.0, 일일 40,000건
GEOCODE_SLEEP = 0.1  # 호출 사이 대기(초)
ADMDONG_VERSION = "ver20261001"  # vuski/admdongkor (SGIS 행정동 경계 가공, CC BY 4.0)
ADMDONG_URL = ("https://raw.githubusercontent.com/vuski/admdongkor/master/"
               f"{ADMDONG_VERSION}/HangJeongDong_{ADMDONG_VERSION}.geojson")
ADMDONG_FILE = DATA_RAW / f"HangJeongDong_{ADMDONG_VERSION}.geojson"

# 서울 생활권 5개 권역: 2030 서울생활권계획 권역 구분표(서울도시공간포털 「2030 생활권계획의 이해」 area_18.pdf,
# 마포 생활권플랜 area_14.pdf). PDF 용량 제한으로 원문 대신 검색 색인의 표 텍스트로 대조(2026-11-02)
REGION = {
    "도심권": ["종로구", "중구", "용산구"],
    "동북권": ["성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구", "노원구"],
    "서북권": ["은평구", "서대문구", "마포구"],
    "서남권": ["양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구"],
    "동남권": ["서초구", "강남구", "송파구", "강동구"],
}
GU_REGION = {gu: r for r, gus in REGION.items() for gu in gus}

# 서울 25개 자치구 시군구 코드(법정동코드 앞 5자리)
SEOUL_GU = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}

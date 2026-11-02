"""02. 전처리: 기간 필터, 금액 정리, 이상치 표시, 중복 표시, 주소 표준화 (analysis_plan.md 4.2의 1~5단계).

입력: data/raw/apt_rent_*.csv
출력: data/interim/rent_clean.parquet
      outputs/tables/preprocess_log.csv   단계별 건수 (4.2의 8단계)
      outputs/tables/dup_ratio_gu.csv     기간별·구별 완전 중복 비율 (행정동별은 04 이후)

행을 지우는 단계는 기간 필터와 MIN_AREA(설정 시)뿐이다.
이상치(trim_out)와 완전 중복(dup_extra)은 열로만 표시하고, 각 지표 단계에서 거른다.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

RAW_FIELDS = [  # 01_collect.py의 FIELDS와 같음. 완전 중복 판정에 씀
    "sggCd", "umdNm", "aptNm", "jibun", "excluUseAr",
    "dealYear", "dealMonth", "dealDay", "deposit", "monthlyRent",
    "floor", "buildYear", "contractTerm", "contractType", "useRRRight",
    "preDeposit", "preMonthlyRent",
    "roadnm", "roadnmsggcd", "roadnmcd", "roadnmseq", "roadnmbcd",
    "roadnmbonbun", "roadnmbubun", "aptSeq",
]
PERIOD_LABEL = {"pre": "시행 전", "post": "시행 후"}

log_rows = []


def log(step: str, rule: str, df: pd.DataFrame, flagged: pd.Series | None = None) -> None:
    """단계별 남은 건수(기간별)와 표시 건수를 기록한다."""
    row = {"단계": step, "기준": rule, "전체": len(df)}
    for p, lab in PERIOD_LABEL.items():
        row[lab] = int((df["period"] == p).sum()) if "period" in df else np.nan
    row["표시 건수"] = int(flagged.sum()) if flagged is not None else np.nan
    for p, lab in PERIOD_LABEL.items():
        row[f"표시({lab})"] = int((flagged & (df["period"] == p)).sum()) if flagged is not None else np.nan
    log_rows.append(row)
    print(f"{step:<22} 전체 {len(df):>9,}" + (f"  표시 {int(flagged.sum()):,}" if flagged is not None else ""))


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip().replace("", np.nan))


def main() -> None:
    # 비교 기간 계약월 파일만 읽는다 (사이 기간 2020.8.~2022.7. 파일은 진단 전용)
    months = {p.strftime("%Y%m") for s, e in config.PERIODS.values()
              for p in pd.period_range(s[:7], e[:7], freq="M")}
    files = sorted(f for f in config.DATA_RAW.glob("apt_rent_*.csv") if f.stem[-6:] in months)
    raw = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files], ignore_index=True)
    raw = raw[RAW_FIELDS]
    log("0. 원자료", f"{len(files)}개 파일", raw)

    # 완전 중복은 원자료 항목 기준으로 판정 (같은 그룹의 두 번째 행부터 True)
    raw["dup_extra"] = raw.duplicated(subset=RAW_FIELDS, keep="first")

    # ── 1. 기간 필터 ────────────────────────────────
    df = raw.copy()
    df["contract_date"] = pd.to_datetime(
        df["dealYear"] + "-" + df["dealMonth"].str.zfill(2) + "-" + df["dealDay"].str.zfill(2),
        errors="coerce",
    )
    df["period"] = pd.NA
    for p, (start, end) in config.PERIODS.items():
        df.loc[df["contract_date"].between(start, end), "period"] = p
    n_bad_date = int(df["contract_date"].isna().sum())
    df = df[df["period"].notna()].copy()
    start_year = df["period"].map({p: int(s[:4]) for p, (s, _) in config.PERIODS.items()})
    # 1년차: 시작연도 8월 ~ 다음 해 7월
    first_end = pd.to_datetime((start_year + 1).astype(str) + "-07-31")
    df["year_in_period"] = np.where(df["contract_date"] <= first_end, 1, 2)
    log("1. 기간 필터", f"계약일 {config.PERIODS['pre']} / {config.PERIODS['post']}, 날짜 변환 실패 {n_bad_date}건", df)

    # ── 2. 금액 정리 ────────────────────────────────
    for src, dst in [("deposit", "deposit"), ("monthlyRent", "monthly_rent"),
                     ("preDeposit", "pre_deposit"), ("preMonthlyRent", "pre_monthly_rent"),
                     ("excluUseAr", "area"), ("floor", "floor_n"), ("buildYear", "build_year")]:
        df[dst] = to_num(df[src])
    # 보증금·월세가 모두 0이거나 비어 있으면 임대료 정보가 없는 계약: 행은 남기고 모든 지표에서 제외
    df["invalid_rent"] = df["deposit"].fillna(0).eq(0) & df["monthly_rent"].fillna(0).eq(0)
    bad_area = df["area"].isna()
    df = df[~bad_area].copy()
    df["rent_type"] = np.where(df["monthly_rent"] > 0, "월세 포함", "순수전세")
    df.loc[df["invalid_rent"], "rent_type"] = pd.NA
    df["dep_per_m2"] = df["deposit"] / df["area"]  # 만 원/㎡
    df["area_r"] = (df["area"] / config.AREA_ROUND).round() * config.AREA_ROUND
    log("2. 금액 정리", f"쉼표 제거·숫자 변환(만 원), 면적 변환 실패 제외 {int(bad_area.sum())}건, "
        "보증금·월세 모두 0 또는 빈 값 invalid_rent 표시(지표 제외)", df, df["invalid_rent"])

    # ── 3. 이상치 ───────────────────────────────────
    if config.MIN_AREA is not None:
        small = df["area"] < config.MIN_AREA
        df = df[~small].copy()
        log("3a. 극소형 제외", f"전용면적 < {config.MIN_AREA}㎡ 제외 {int(small.sum())}건", df)
    else:
        log("3a. 극소형 제외", f"MIN_AREA=None: 제외하지 않음 (참고: {config.SMALL_AREA}㎡ 미만 표시)",
            df, df["area"] < config.SMALL_AREA)

    df["trim_out"] = False
    scope = df["rent_type"] == "순수전세" if config.TRIM_SCOPE == "jeonse" else pd.Series(True, index=df.index)
    for p in config.PERIODS:
        m = scope & (df["period"] == p)
        lo, hi = df.loc[m, "dep_per_m2"].quantile([config.TRIM_PCT, 1 - config.TRIM_PCT])
        df.loc[m, "trim_out"] = (df.loc[m, "dep_per_m2"] < lo) | (df.loc[m, "dep_per_m2"] > hi)
        print(f"   {PERIOD_LABEL[p]} 절사 경계(만 원/㎡): {lo:.1f} ~ {hi:.1f}")
    log("3b. ㎡당 보증금 절사", f"기간별 상하위 {config.TRIM_PCT:.0%}, 대상 {config.TRIM_SCOPE}, 행 유지·trim_out 표시",
        df, df["trim_out"])

    # ── 4. 완전 중복 ─────────────────────────────────
    log("4. 완전 중복", f"DEDUP_MODE={config.DEDUP_MODE}: 행 유지·dup_extra 표시, 해제 여부 항목 없음",
        df, df["dup_extra"])
    if config.DEDUP_MODE == "drop":
        df = df[~df["dup_extra"]].copy()
        log("4. 완전 중복 제거", "dup_extra 행 제거", df)

    # ── 5. 주소 표준화 ───────────────────────────────
    df["gu"] = df["sggCd"].map(config.SEOUL_GU)
    no_jibun = df["jibun"].str.strip() == ""
    df["address"] = "서울특별시 " + df["gu"] + " " + df["umdNm"] + " " + df["jibun"].str.strip()
    df.loc[no_jibun, "address"] = pd.NA
    log("5. 주소 표준화", f"서울특별시+구+법정동+지번, 지번 없음 {int(no_jibun.sum())}건", df)

    # 공공임대로 보이는 단지: 행은 남기고 표시. 지표 단계에서 EXCLUDE_PUBLIC_RENTAL에 따라 제외
    df["public_rental"] = df["aptNm"].str.contains(config.PUBLIC_RENTAL_PATTERN, regex=True)
    log("5a. 공공임대 표시", "단지명 키워드(config.PUBLIC_RENTAL_PATTERN), 행 유지·public_rental 표시 [확인 필요]",
        df, df["public_rental"])

    # 중복 비율 (기간별·구별)
    dup = (df.groupby(["period", "sggCd", "gu"])
             .agg(n=("dup_extra", "size"), n_dup_extra=("dup_extra", "sum"))
             .reset_index())
    dup["dup_pct"] = (dup["n_dup_extra"] / dup["n"] * 100).round(2)

    keep = ["sggCd", "gu", "umdNm", "aptSeq", "aptNm", "jibun", "address", "roadnm",
            "contract_date", "period", "year_in_period",
            "deposit", "monthly_rent", "rent_type", "area", "area_r", "dep_per_m2",
            "floor_n", "build_year", "contractTerm", "contractType", "useRRRight",
            "pre_deposit", "pre_monthly_rent", "invalid_rent", "trim_out", "dup_extra", "public_rental"]
    out = df[keep].rename(columns={"floor_n": "floor"})

    config.DATA_INTERIM.mkdir(parents=True, exist_ok=True)
    config.OUT_TAB.mkdir(parents=True, exist_ok=True)
    out.to_parquet(config.DATA_INTERIM / "rent_clean.parquet", index=False)
    pd.DataFrame(log_rows).to_csv(config.OUT_TAB / "preprocess_log.csv", index=False, encoding="utf-8-sig")
    dup.to_csv(config.OUT_TAB / "dup_ratio_gu.csv", index=False, encoding="utf-8-sig")
    print(f"저장: rent_clean.parquet {len(out):,}행")


if __name__ == "__main__":
    main()

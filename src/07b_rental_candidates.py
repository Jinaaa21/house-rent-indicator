"""07b. 자료 기반 임대 단지 후보: 갱신 계약의 보증금 인상률이 정확히 5%(±0.05%p)에 몰린 단지.

제도상 5% 상한이 걸린 임대(공공임대, 청년주택 등)인데 단지명 키워드로 걸리지 않는 단지를 찾기 위한 점검 목록.
후보는 제외하지 않는다. 공식 목록과 대조하지 못했으므로 모두 [확인 필요].

대상: 시행 후 기간, 공공임대 표시(public_rental)가 아닌 단지, 갱신 계약(preDeposit > 0) ≥ MIN_RENEW_CAND
출력: outputs/tables/rental_candidates.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

MIN_RENEW_CAND = 30
CAP_TOL = 0.0005
TOP = 30


def main() -> None:
    d = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    d = d[(d["period"] == "post") & ~d["invalid_rent"] & ~d["public_rental"]
          & d["contractType"].eq("갱신") & (d["pre_deposit"] > 0)].copy()
    d["inc"] = d["deposit"] / d["pre_deposit"] - 1
    d["cap5"] = (d["inc"] - 0.05).abs() <= CAP_TOL
    d["used"] = d["useRRRight"].eq("사용")
    seoul5 = d["cap5"].mean()

    g = d.groupby("aptSeq").agg(
        단지명=("aptNm", "first"), 자치구=("adm_gu", "first"), 행정동=("adm_nm", "first"),
        준공연도=("build_year", "first"), 갱신=("cap5", "size"), 정확히5_비율=("cap5", "mean"),
        사용_비중=("used", "mean"), 월세포함_비중=("rent_type", lambda s: (s == "월세 포함").mean()))
    g["행정동"] = g["행정동"].str.split().str[-1]
    u = d[d["used"]].groupby("aptSeq")["cap5"].agg(["size", "mean"]).rename(
        columns={"size": "사용_갱신", "mean": "사용 중 정확히5"})
    b = d[~d["used"]].groupby("aptSeq")["cap5"].agg(["size", "mean"]).rename(
        columns={"size": "빈값_갱신", "mean": "빈 값 중 정확히5"})
    g = g.join(u).join(b)
    g = g[g["갱신"] >= MIN_RENEW_CAND].sort_values("정확히5_비율", ascending=False)
    g["판단"] = "후보 [확인 필요]: 공식 목록과 대조 못 함"
    top = g.head(TOP)
    for c in ["정확히5_비율", "사용_비중", "월세포함_비중", "사용 중 정확히5", "빈 값 중 정확히5"]:
        top[c] = (top[c] * 100).round(1)
    top.to_csv(config.OUT_TAB / "rental_candidates.csv", encoding="utf-8-sig")
    print(f"갱신 {MIN_RENEW_CAND}건 이상 단지 {len(g)}개, 서울 갱신 계약 중 정확히 5% 비율 {seoul5 * 100:.1f}%")
    print(f"정확히 5% 비율 50% 이상 단지 {int((g['정확히5_비율'] >= 0.5).sum())}개")
    cols = ["단지명", "자치구", "준공연도", "갱신", "정확히5_비율", "사용_비중", "사용 중 정확히5", "빈 값 중 정확히5",
            "월세포함_비중"]
    print(top[cols].to_string())


if __name__ == "__main__":
    main()

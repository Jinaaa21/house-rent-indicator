"""08d. ΔLQ의 평균으로의 회귀 점검.

원래 점검: corr(LQ_전, LQ_후 − LQ_전) — 같은 LQ_전이 양쪽에 들어가 측정 오차만으로도 음의 상관이 생긴다.
분리 점검: 기준 LQ = 시행 전 1년차 LQ, 변화 = 시행 후 LQ − 시행 전 2년차 LQ.
  기준과 변화가 서로 다른 계약으로 계산되므로, 측정 오차로 생기는 음의 상관이 빠진다.
LQ의 서울 기준 비율은 각 구간(시행 전 1년차, 2년차, 시행 후)과 같은 범위의 계약으로 구한다.
최소 건수: 시행 전 1년차·2년차·시행 후 각각 N ≥ MIN_N_LQ, 해석 유보 동 제외.

출력: outputs/tables/lq_regression_check.csv
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def lq(r: pd.DataFrame, mask: pd.Series, name: str) -> pd.DataFrame:
    x = r[mask]
    m = x["rent_type"].eq("월세 포함")
    g = x.assign(M=m).groupby("adm_cd").agg(**{f"N_{name}": ("M", "size"), f"M_{name}": ("M", "sum")})
    g[f"LQ_{name}"] = g[f"M_{name}"] / g[f"N_{name}"] / m.mean()
    return g


def main() -> None:
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    rent = rent[~rent["invalid_rent"]]
    if config.EXCLUDE_PUBLIC_RENTAL:
        rent = rent[~rent["public_rental"]]
    rows = []
    for v, r in [("dLQ_all", rent), ("dLQ_exist", rent[rent["build_year"] <= config.EXIST_MAX_BUILD_YEAR])]:
        pre, post = r["period"].eq("pre"), r["period"].eq("post")
        t = (lq(r, pre, "pre").join(lq(r, post, "post"))
               .join(lq(r, pre & r["year_in_period"].eq(1), "pre1"))
               .join(lq(r, pre & r["year_in_period"].eq(2), "pre2")))
        t = t[~t.index.isin(list(config.HOLD_ADMDONG))]
        ok_a = (t["N_pre"] >= config.MIN_N_LQ) & (t["N_post"] >= config.MIN_N_LQ)
        ok_b = ok_a & (t["N_pre1"] >= config.MIN_N_LQ) & (t["N_pre2"] >= config.MIN_N_LQ)
        a, b = t[ok_a], t[ok_b]
        d_orig = a["LQ_post"] - a["LQ_pre"]
        d_split = b["LQ_post"] - b["LQ_pre2"]
        rows += [
            {"버전": v, "점검": "원래: corr(LQ_전, LQ_후 − LQ_전)", "동 수": len(a),
             "Pearson": a["LQ_pre"].corr(d_orig), "Spearman": a["LQ_pre"].rank().corr(d_orig.rank())},
            {"버전": v, "점검": "원래(같은 동 집합)", "동 수": len(b),
             "Pearson": b["LQ_pre"].corr(b["LQ_post"] - b["LQ_pre"]),
             "Spearman": b["LQ_pre"].rank().corr((b["LQ_post"] - b["LQ_pre"]).rank())},
            {"버전": v, "점검": "분리: corr(LQ_전1년차, LQ_후 − LQ_전2년차)", "동 수": len(b),
             "Pearson": b["LQ_pre1"].corr(d_split), "Spearman": b["LQ_pre1"].rank().corr(d_split.rank())},
            {"버전": v, "점검": "참고: corr(LQ_전1년차, LQ_전2년차)", "동 수": len(b),
             "Pearson": b["LQ_pre1"].corr(b["LQ_pre2"]), "Spearman": b["LQ_pre1"].rank().corr(b["LQ_pre2"].rank())},
            {"버전": v, "점검": "참고: corr(LQ_전1년차, LQ_전2년차 − LQ_전1년차) (시행 전 안의 1년 변화)", "동 수": len(b),
             "Pearson": b["LQ_pre1"].corr(b["LQ_pre2"] - b["LQ_pre1"]),
             "Spearman": b["LQ_pre1"].rank().corr((b["LQ_pre2"] - b["LQ_pre1"]).rank())},
        ]
        # 도심권(중구 일대) 확인용
        if v == "dLQ_exist":
            dong = pd.read_csv(config.OUT_TAB / "admdong_counts.csv", dtype={"adm_cd": str}).set_index("adm_cd")
            bb = b.join(dong[["adm_gu", "adm_nm"]])
            bb["region"] = bb["adm_gu"].map(config.GU_REGION)
            bb["d_split"] = d_split
            print("권역별 중위(기존 단지): 분리 변화(LQ_후 − LQ_전2년차)",
                  bb.groupby("region")["d_split"].median().round(3).to_dict())
            print("권역별 중위: 원래 ΔLQ", bb.assign(d=bb["LQ_post"] - bb["LQ_pre"]).groupby("region")["d"].median().round(3).to_dict())
            sel = bb[bb["adm_nm"].str.contains("장충동|신당5동|중림동|광희동|신당동$")]
            print(sel[["adm_nm", "N_pre1", "N_pre2", "LQ_pre1", "LQ_pre2", "LQ_post"]].round(2).to_string())
    res = pd.DataFrame(rows)
    res.to_csv(config.OUT_TAB / "lq_regression_check.csv", index=False, encoding="utf-8-sig")
    print(res.round(3).to_string(index=False))


if __name__ == "__main__":
    main()

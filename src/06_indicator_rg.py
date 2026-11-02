"""06. 지표 C: 상대 누적 상승률 RG (CLAUDE.md 3.2).

g_c,t = ln(P_c,t,2년차 / P_c,t,1년차)   c: 단지(aptSeq) × 전용면적(area_r) 묶음
g_i,t = median_{c ∈ i} g_c,t,          RG_i = g_i,후 − g_i,전
P: 순수전세(월세 0) 계약의 ㎡당 보증금 중위값. trim_out·invalid_rent 제외.
각 기간 시작 전년도까지 준공된 단지만 사용(RG_MAX_BUILD_YEAR). 공공임대 표시 단지 제외(EXCLUDE_PUBLIC_RENTAL).
1년차·2년차 모두 거래가 있는 묶음만 쓰고, 두 기간 모두 매칭 묶음 ≥ MIN_CELLS_RG인 동만 RG를 계산.
공공임대를 포함한 RG는 RG_incl 열로 함께 저장(민감도). 동별 순위보다 공간 패턴·권역 비교로 해석한다.

입력: data/interim/rent_admdong.parquet, outputs/tables/admdong_counts.csv
출력: data/processed/indicator_rg.csv, data/interim/rg_cells.parquet (기본), rg_cells_incl.parquet
      outputs/tables/rg_summary.csv, rg_top_bottom.csv, rg_filter_log.csv, rg_public_sensitivity.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OUT = config.OUT_TAB


def build_cells(rent: pd.DataFrame, exclude_public: bool) -> tuple[pd.DataFrame, list]:
    flog = [{"단계": "행정동 결합 후 전체", "건수": len(rent)}]
    d = rent[rent["rent_type"].eq("순수전세") & ~rent["invalid_rent"]]
    flog.append({"단계": "순수전세", "건수": len(d)})
    if exclude_public:
        d = d[~d["public_rental"]]
        flog.append({"단계": "공공임대 표시 단지 제외", "건수": len(d)})
    d = d[~d["trim_out"]]
    flog.append({"단계": f"㎡당 보증금 절사(상하위 {config.TRIM_PCT:.0%}) 제외", "건수": len(d)})
    d = d[d["build_year"] <= d["period"].map(config.RG_MAX_BUILD_YEAR)]
    flog.append({"단계": f"준공연도 조건(전 ≤ {config.RG_MAX_BUILD_YEAR['pre']}, "
                       f"후 ≤ {config.RG_MAX_BUILD_YEAR['post']})", "건수": len(d)})
    cell = (d.groupby(["period", "adm_cd", "aptSeq", "area_r", "year_in_period"])["dep_per_m2"]
              .agg(["median", "size"]).unstack("year_in_period"))
    cell.columns = [f"{a}_y{b}" for a, b in cell.columns]
    n_cells_all = len(cell)
    cell = cell.dropna(subset=["median_y1", "median_y2"]).reset_index()
    cell["g"] = np.log(cell["median_y2"] / cell["median_y1"])
    flog.append({"단계": "매칭 묶음(1·2년차 모두 거래)", "건수": int(cell[["size_y1", "size_y2"]].sum().sum()),
                 "묶음": len(cell), "전체 묶음": n_cells_all})
    return cell, flog


def dong_rg(cell: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    g = cell.groupby(["adm_cd", "period"]).agg(g=("g", "median"), cells=("g", "size")).unstack("period")
    g.columns = [f"{a}_{p}" for a, p in g.columns]
    g = g.reindex(index)
    g[["cells_pre", "cells_post"]] = g[["cells_pre", "cells_post"]].fillna(0).astype(int)
    g["ok"] = (g["cells_pre"] >= config.MIN_CELLS_RG) & (g["cells_post"] >= config.MIN_CELLS_RG)
    g["RG"] = (g["g_post"] - g["g_pre"]).where(g["ok"])
    return g


def main() -> None:
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    cell, flog = build_cells(rent, config.EXCLUDE_PUBLIC_RENTAL)
    cell_incl, _ = build_cells(rent, False)
    pd.DataFrame(flog).to_csv(OUT / "rg_filter_log.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(flog).to_string(index=False))
    cell.to_parquet(config.DATA_INTERIM / "rg_cells.parquet", index=False)
    cell_incl.to_parquet(config.DATA_INTERIM / "rg_cells_incl.parquet", index=False)

    dong = pd.read_csv(OUT / "admdong_counts.csv", dtype={"adm_cd": str, "adm_cd2": str})
    out = dong[["adm_cd", "adm_cd2", "adm_gu", "adm_nm"]].set_index("adm_cd")
    out = out.join(dong_rg(cell, out.index))
    inc = dong_rg(cell_incl, out.index)
    out["RG_incl"], out["ok_incl"] = inc["RG"], inc["ok"]
    out["hold"] = out.index.isin(list(config.HOLD_ADMDONG))
    out["status"] = np.select([~out["ok"], out["hold"]], ["자료 부족", "해석 유보"], "정상")
    out["dong"] = out["adm_nm"].str.split().str[-1]
    out.reset_index().to_csv(config.DATA_PROCESSED / "indicator_rg.csv", index=False, encoding="utf-8-sig")

    ok = out[out["ok"]]
    print(f"\n서울 묶음 중위 g: 시행 전 {cell.loc[cell.period == 'pre', 'g'].median():.4f}, "
          f"시행 후 {cell.loc[cell.period == 'post', 'g'].median():.4f}")
    rows = []
    for col in ["g_pre", "g_post", "RG"]:
        s = ok[col].describe(percentiles=[.1, .25, .5, .75, .9])
        rows.append({"항목": col, **{k: s[k] for k in ["count", "mean", "std", "min", "10%", "25%", "50%",
                                                      "75%", "90%", "max"]}})
    summ = pd.DataFrame(rows)
    summ.to_csv(OUT / "rg_summary.csv", index=False, encoding="utf-8-sig")
    print(summ.round(4).to_string(index=False))
    print(f"자료 부족 {int((~out['ok']).sum())}개 동 (시행 전 묶음 미달 {int((out['cells_pre'] < config.MIN_CELLS_RG).sum())}, "
          f"시행 후 미달 {int((out['cells_post'] < config.MIN_CELLS_RG).sum())}), "
          f"해석 유보 {int(ok['hold'].sum())}, RG>0 {int((ok['RG'] > 0).sum())}개 동")

    cols = ["adm_gu", "dong", "cells_pre", "cells_post", "g_pre", "g_post", "RG"]
    ok2 = ok[~ok["hold"]]
    tb = []
    for side, part in [("상위", ok2.nlargest(10, "RG")), ("하위", ok2.nsmallest(10, "RG"))]:
        tb.append(part[cols].assign(구분=side, 순위=range(1, 11)))
    pd.concat(tb).to_csv(OUT / "rg_top_bottom.csv", index=False, encoding="utf-8-sig")

    # 민감도: 공공임대 포함
    b = out[out["ok"] & out["ok_incl"] & ~out["hold"]].copy()
    b["diff"] = b["RG_incl"] - b["RG"]
    print(f"\n[공공임대 포함 RG] 동 {len(b)}개, Pearson {b['RG'].corr(b['RG_incl']):.3f}, "
          f"|차이| 최대 {b['diff'].abs().max():.4f}")
    b.reindex(b["diff"].abs().sort_values(ascending=False).index).head(10)[
        ["adm_gu", "dong", "RG", "RG_incl", "diff"]].to_csv(OUT / "rg_public_sensitivity.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()

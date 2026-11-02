"""09. 공간 통계: 전역 Moran's I (CLAUDE.md 5.1).

지표: dLQ_all, dLQ_exist, RG, U. 자료 부족·해석 유보 동은 제외하고, 남은 동으로 가중행렬을 만든다.
가중행렬: 퀸 인접(기본), k-최근접 k=6(강건성, 동 중심점 기준). 행 표준화. 전역 순열 999회, LISA 순열 99,999회.
퀸 인접에서 이웃이 없는 동(섬)은 목록을 기록하고 Moran's I 계산에서 뺀다(k-최근접에는 포함).

입력: data/processed/indicator_lq.csv, indicator_rg.csv, indicator_renewal.csv, config.ADMDONG_FILE
출력: outputs/tables/moran_global.csv, moran_islands.csv, lisa_dLQ_exist.csv, lisa_RG.csv
"""
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from esda import fdr
from esda.moran import Moran, Moran_Local
from libpysal.weights import KNN, Queen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)  # 섬 경고는 표로 따로 기록
OUT = config.OUT_TAB
PERM = 999
# LISA: 동 약 400개에 FDR(0.05)을 적용하면 가장 작은 p값이 약 0.000125 이하여야 하므로
# 최소 p값이 1/(PERM+1)인 순열 검정은 99,999회가 필요하다
PERM_LISA = 99_999
SEED = 20261102


def load() -> gpd.GeoDataFrame:
    g = gpd.read_file(config.ADMDONG_FILE)
    g = g[g["sidonm"] == "서울특별시"][["adm_cd", "geometry"]].to_crs(epsg=5179)
    lq = pd.read_csv(config.DATA_PROCESSED / "indicator_lq.csv", dtype={"adm_cd": str})
    rg = pd.read_csv(config.DATA_PROCESSED / "indicator_rg.csv", dtype={"adm_cd": str})
    rn = pd.read_csv(config.DATA_PROCESSED / "indicator_renewal.csv", dtype={"adm_cd": str})
    df = (lq[["adm_cd", "adm_gu", "dong", "hold", "dLQ_all", "ok_all", "dLQ_exist", "ok_exist"]]
          .merge(rg[["adm_cd", "RG", "ok"]].rename(columns={"ok": "ok_rg"}), on="adm_cd")
          .merge(rn[["adm_cd", "U", "ok"]].rename(columns={"ok": "ok_u"}), on="adm_cd"))
    return g.merge(df, on="adm_cd")


def moran_row(gdf: gpd.GeoDataFrame, col: str, wname: str) -> tuple[dict, list]:
    if wname == "queen":
        w = Queen.from_dataframe(gdf, use_index=False)
    else:
        w = KNN.from_dataframe(gdf.set_geometry(gdf.geometry.centroid), k=6, use_index=False)
    islands = list(w.islands)
    sub = gdf
    if islands:
        sub = gdf.drop(gdf.index[islands]).reset_index(drop=True)
        w = Queen.from_dataframe(sub, use_index=False)
    w.transform = "r"
    np.random.seed(SEED)  # esda Moran은 seed 인자가 없어 전역 시드로 순열 재현
    m = Moran(sub[col].to_numpy(), w, permutations=PERM)
    return ({"지표": col, "가중행렬": "퀸 인접" if wname == "queen" else "k-최근접(k=6)", "동 수": len(sub),
             "섬 제외": len(islands), "Moran's I": m.I, "기댓값 E[I]": m.EI, "z(순열)": m.z_sim,
             "p(순열, 999회)": m.p_sim}, [gdf.iloc[i][["adm_cd", "adm_gu", "dong"]].tolist() for i in islands])


CLUSTER = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}


def lisa(gdf: gpd.GeoDataFrame, col: str) -> pd.DataFrame:
    """국지적 Moran(LISA), 퀸 인접, 순열 PERM_LISA회. 유의수준 0.05와 FDR(0.05) 두 기준."""
    w = Queen.from_dataframe(gdf, use_index=False)
    sub = gdf.drop(gdf.index[list(w.islands)]).reset_index(drop=True) if w.islands else gdf
    w = Queen.from_dataframe(sub, use_index=False)
    w.transform = "r"
    np.random.seed(SEED)
    lm = Moran_Local(sub[col].to_numpy(), w, permutations=PERM_LISA, seed=SEED, keep_simulations=False)
    thr = fdr(lm.p_sim, 0.05)
    out = sub[["adm_cd", "adm_gu", "dong", col]].copy()
    out["Ii"], out["p_sim"], out["quad"] = lm.Is, lm.p_sim, [CLUSTER[q] for q in lm.q]
    out["cluster_005"] = np.where(out["p_sim"] <= 0.05, out["quad"], "유의하지 않음")
    out["cluster_fdr"] = np.where(out["p_sim"] <= thr, out["quad"], "유의하지 않음")
    out.attrs["fdr_threshold"] = thr
    return out


def main() -> None:
    gdf = load()
    for col, okc in [("dLQ_exist", "ok_exist"), ("RG", "ok_rg")]:
        sub = gdf[gdf[okc].astype(bool) & ~gdf["hold"].astype(bool) & gdf[col].notna()].reset_index(drop=True)
        lt = lisa(sub, col)
        lt.to_csv(OUT / f"lisa_{col}.csv", index=False, encoding="utf-8-sig")
        print(f"\n[LISA {col}] 동 {len(lt)}개, FDR 기준 p ≤ {lt.attrs['fdr_threshold']:.4f}")
        cnt = pd.DataFrame({"p ≤ 0.05": lt["cluster_005"].value_counts(), "FDR": lt["cluster_fdr"].value_counts()})
        print(cnt.fillna(0).astype(int).to_string())
        for q in ["HH", "LL"]:
            print(f"  {q}(0.05): " + ", ".join(lt.loc[lt["cluster_005"] == q, "adm_gu"] + " " + lt.loc[lt["cluster_005"] == q, "dong"]))
    rows, isl = [], []
    for col, okc in [("dLQ_all", "ok_all"), ("dLQ_exist", "ok_exist"), ("RG", "ok_rg"), ("U", "ok_u")]:
        sub = gdf[gdf[okc].astype(bool) & ~gdf["hold"].astype(bool) & gdf[col].notna()].reset_index(drop=True)
        for wname in ["queen", "knn"]:
            r, islands = moran_row(sub, col, wname)
            rows.append(r)
            for a in islands:
                isl.append({"지표": col, "가중행렬": r["가중행렬"], "adm_cd": a[0], "자치구": a[1], "행정동": a[2]})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "moran_global.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(isl, columns=["지표", "가중행렬", "adm_cd", "자치구", "행정동"]).to_csv(
        OUT / "moran_islands.csv", index=False, encoding="utf-8-sig")
    print(res.round(4).to_string(index=False))
    print("\n이웃 없는 동(섬):" + (" 없음" if not isl else ""))
    if isl:
        print(pd.DataFrame(isl).to_string(index=False))


if __name__ == "__main__":
    main()

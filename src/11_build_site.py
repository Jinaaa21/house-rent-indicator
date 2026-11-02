"""11. 정적 사이트(site/)용 데이터 만들기. 브라우저(site/app.js)가 이 파일들로 지도·차트를 직접 그린다.

출력: site/data/admdong.geojson  서울 행정동 경계(간소화, 속성은 adm_cd만)
      site/data/gu.geojson       자치구 경계(행정동을 합침)
      site/data/dongs.json       행정동별 지표·구간·LISA·진단 값
      site/data/summary.json     서울 요약, 월별 추이, 자치구 RG, Moran's I, 인상률 분포, 전처리 건수 등
"""
import importlib
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

SITE = config.ROOT / "site" / "data"
T, P = config.OUT_TAB, config.DATA_PROCESSED
SIMPLIFY_M = 25  # 경계 간소화 허용 오차(m, EPSG:5179)


def num(v, d=4):
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return None
    return round(float(v), d)


def boolish(v):
    return str(v) == "True"


def write(name, obj):
    with open(SITE / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{name}: {(SITE / name).stat().st_size / 1024:.0f} KB")


def geometry():
    g = gpd.read_file(config.ADMDONG_FILE)
    g = g[g["sidonm"] == "서울특별시"][["adm_cd", "sggnm", "geometry"]].to_crs(epsg=5179)
    gu = g.dissolve(by="sggnm", as_index=False)
    for df, key, name in [(g, "adm_cd", "admdong.geojson"), (gu, "sggnm", "gu.geojson")]:
        s = df[[key, "geometry"]].copy()
        s["geometry"] = s.geometry.simplify(SIMPLIFY_M, preserve_topology=True)
        s = s.to_crs(epsg=4326).rename(columns={"sggnm": "gu"})
        gj = json.loads(s.to_json(drop_id=True))
        def rnd(c):
            return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 5), round(c[1], 5)]
        for f in gj["features"]:
            f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
        write(name, gj)


def dongs():
    rd = lambda f: pd.read_csv(P / f, dtype={"adm_cd": str})
    lq, rg, rn, ci = rd("indicator_lq.csv"), rd("indicator_rg.csv"), rd("indicator_renewal.csv"), rd("indicator_ci.csv")
    ld = pd.read_csv(T / "lisa_dLQ_exist.csv", dtype={"adm_cd": str}).set_index("adm_cd")
    lr = pd.read_csv(T / "lisa_RG.csv", dtype={"adm_cd": str}).set_index("adm_cd")

    # 신고 증가배수 R: 08과 같은 정의(전체 계약 / 준공 2017년 이하)
    diag = importlib.import_module("08_diagnostics")
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    rent = rent[~rent["invalid_rent"]]
    r_all = diag.dong_table(rent).set_index("adm_cd")
    r_ex = diag.dong_table(rent[rent["build_year"] <= config.EXIST_MAX_BUILD_YEAR]).set_index("adm_cd")

    m = (lq.set_index("adm_cd")
           .join(rg.set_index("adm_cd")[["RG", "ok", "g_pre", "g_post", "cells_pre", "cells_post"]].rename(columns={"ok": "ok_rg"}))
           .join(rn.set_index("adm_cd")[["U", "U_lo", "U_hi", "U_upper", "REN", "blank_type_share", "n_renew", "n_used", "ok"]]
                 .rename(columns={"ok": "ok_u"}))
           .join(ci.set_index("adm_cd")[[c for c in ci.columns if c.endswith(("_lo", "_hi", "_sig"))]]))
    out = []
    for cd, r in m.iterrows():
        def ind(v, ok, lo=None, hi=None, sig=None):
            return {"v": num(r[v]) if ok else None, "lo": num(r[lo]) if lo and ok else None,
                    "hi": num(r[hi]) if hi and ok else None, "sig": boolish(r[sig]) if sig and ok else None}
        o = {
            "cd": cd, "gu": r["adm_gu"], "nm": r["dong"], "region": config.GU_REGION.get(r["adm_gu"]),
            "hold": bool(r["hold"]),
            "dLQ_all": ind("dLQ_all", bool(r["ok_all"]), "dLQ_all_lo", "dLQ_all_hi", "dLQ_all_sig"),
            "dLQ_exist": ind("dLQ_exist", bool(r["ok_exist"]), "dLQ_exist_lo", "dLQ_exist_hi", "dLQ_exist_sig"),
            "RG": ind("RG", bool(r["ok_rg"]), "RG_lo", "RG_hi", "RG_sig"),
            "U": ind("U", bool(r["ok_u"]), "U_lo", "U_hi"),
            "U_upper": num(r["U_upper"]) if r["ok_u"] else None,
            "N_pre": int(r["N_pre_all"]) if pd.notna(r["N_pre_all"]) else 0,
            "N_post": int(r["N_post_all"]) if pd.notna(r["N_post_all"]) else 0,
            "LQ_pre": num(r["LQ_pre_exist"], 3), "LQ_post": num(r["LQ_post_exist"], 3),
            "g_pre": num(r["g_pre"]), "g_post": num(r["g_post"]),
            "cells": [int(r["cells_pre"]) if pd.notna(r["cells_pre"]) else 0,
                      int(r["cells_post"]) if pd.notna(r["cells_post"]) else 0],
            "n_renew": int(r["n_renew"]) if pd.notna(r["n_renew"]) else 0,
            "blank": num(r["blank_type_share"], 3),
            "lisa_dLQ": [ld.at[cd, "cluster_fdr"], ld.at[cd, "cluster_005"]] if cd in ld.index else None,
            "lisa_RG": [lr.at[cd, "cluster_fdr"], lr.at[cd, "cluster_005"]] if cd in lr.index else None,
            "R_all": [num(r_all.at[cd, "R"], 3), num(r_all.at[cd, "dLQ"], 4)]
                     if cd in r_all.index and r_all.at[cd, "ok"] else None,
            "R_exist": [num(r_ex.at[cd, "R"], 3), num(r_ex.at[cd, "dLQ"], 4)]
                       if cd in r_ex.index and r_ex.at[cd, "ok"] else None,
        }
        out.append(o)
    write("dongs.json", out)


def summary():
    s = {}
    mon = pd.read_csv(T / "diag_monthly_seoul.csv", dtype={"ym": str})
    s["monthly"] = [{"ym": r.ym, "n": int(r.계약수), "share": num(r["월세 포함 비중(%)"], 2), "seg": r.구간}
                    for _, r in mon.iterrows()]
    s["dates"] = {"law": config.LAW_DATE, "report": config.REPORTING_DATE}
    pl = pd.read_csv(T / "diag_reporting_placebo.csv")
    s["placebo"] = [{"name": r.비교, "a": r["앞 6개월"] if pd.notna(r["앞 6개월"]) else None,
                     "b": r["뒤 6개월"] if pd.notna(r["뒤 6개월"]) else None, "diff": num(r["차이(%p)"], 2)}
                    for _, r in pl.iterrows()]
    per = pd.read_csv(T / "diag_seoul_period.csv")
    s["period"] = [{"period": r.period, "yr": str(r.year_in_period), "n": int(r.계약수), "share": num(r["월세 포함 비중(%)"], 2)}
                   for _, r in per.iterrows()]
    mor = pd.read_csv(T / "moran_global.csv")
    s["moran"] = [{"ind": r.지표, "w": r.가중행렬, "n": int(r["동 수"]), "I": num(r["Moran's I"], 4),
                   "p": num(r["p(순열, 999회)"], 4)} for _, r in mor.iterrows()]
    gu = pd.read_csv(T / "rg_gu_ci.csv")
    s["gu_rg"] = [{"gu": r.자치구, "region": config.GU_REGION.get(r.자치구), "g_pre": num(r.g_pre), "g_post": num(r.g_post),
                   "RG": num(r.RG), "lo": num(r.RG_lo), "hi": num(r.RG_hi),
                   "note": r.비고 if isinstance(r.비고, str) else ""} for _, r in gu.iterrows()]
    cis = pd.read_csv(T / "ci_summary.csv")
    s["ci"] = {r.지표: {"n": int(r["값 있는 동"]), "sig": int(r["구간이 0 제외"])} for _, r in cis.iterrows()}
    lisa = {}
    for c in ["dLQ_exist", "RG"]:
        t = pd.read_csv(T / f"lisa_{c}.csv")
        lisa[c] = {"n": len(t), "fdr": t["cluster_fdr"].value_counts().to_dict(), "p05": t["cluster_005"].value_counts().to_dict()}
    s["lisa"] = lisa
    plog = pd.read_csv(T / "preprocess_log.csv")
    s["preprocess"] = [{"step": r.단계, "rule": r.기준, "n": int(r.전체),
                        "flag": [None if pd.isna(r["표시(시행 전)"]) else int(r["표시(시행 전)"]),
                                 None if pd.isna(r["표시(시행 후)"]) else int(r["표시(시행 후)"])]}
                       for _, r in plog.iterrows()]
    s["region_order"] = list(config.REGION)
    sc = pd.read_csv(T / "stock_corr.csv")
    s["stock_corr"] = [{"ind": r.지표, "feat": r["재고 특성"], "n": int(r["동 수"]),
                        "p": num(r.Pearson, 3), "p_lo": num(r.P_lo, 3), "p_hi": num(r.P_hi, 3),
                        "s": num(r.Spearman, 3), "s_lo": num(r.S_lo, 3), "s_hi": num(r.S_hi, 3)}
                       for _, r in sc.iterrows()]

    # 갱신 계약 보증금 인상률 분포(순수전세): 1% 구간, 0%·5%가 구간 가운데
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    d = rent[(rent["period"] == "post") & ~rent["invalid_rent"] & ~rent["public_rental"]
             & rent["contractType"].eq("갱신") & (rent["pre_deposit"] > 0)].copy()
    d["inc"] = d["deposit"] / d["pre_deposit"] - 1
    used = d["useRRRight"].eq("사용")
    bins = np.round(np.arange(-0.205, 0.41, 0.01), 3)
    hist = {}
    for lab, mask in [("used", used), ("blank", ~used)]:
        x = d.loc[mask & d["rent_type"].eq("순수전세"), "inc"]
        cnt, _ = np.histogram(x.clip(bins[0], bins[-1] - 1e-9), bins=bins)
        hist[lab] = {"n": int(len(x)), "counts": cnt.tolist(), "median": num(x.median(), 4),
                     "over5": num((x > 0.0505).mean(), 4), "at5": num(((x - 0.05).abs() <= 0.0005).mean(), 4),
                     "down": num((x < 0).mean(), 4)}
    xo = d.loc[used & d["rent_type"].eq("순수전세"), "inc"]
    cnt, _ = np.histogram(xo[xo > 0.0505].clip(bins[0], bins[-1] - 1e-9), bins=bins)
    hist["used_over5"] = {"counts": cnt.tolist()}
    s["inc_hist"] = {"edges": bins.tolist(), **hist}
    tot = rent[(rent["period"] == "post") & ~rent["invalid_rent"] & ~rent["public_rental"]]
    ct, rr = tot["contractType"].fillna(""), tot["useRRRight"].fillna("")
    n_renew = int(ct.eq("갱신").sum())
    s["renewal"] = {"n": len(tot), "new": int(ct.eq("신규").sum()), "renew": n_renew, "blank": int(ct.eq("").sum()),
                    "used": int((ct.eq("갱신") & rr.eq("사용")).sum())}
    rn = pd.read_csv(P / "indicator_renewal.csv")
    s["renewal"]["U_upper_seoul"] = num((rn["n_used"].sum() + rn["n_blank5"].sum()) / rn["n_renew"].sum(), 4)
    write("summary.json", s)


def main():
    SITE.mkdir(parents=True, exist_ok=True)
    geometry()
    dongs()
    summary()


if __name__ == "__main__":
    main()

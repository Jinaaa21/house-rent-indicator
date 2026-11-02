"""06b. 지표 불확실성: 동별 부트스트랩 90% 구간 (최소 건수 기준은 그대로).

- dLQ_all, dLQ_exist: 동·기간별로 계약을 복원추출(N개). 월세 포함 여부가 0/1이므로
  복원추출한 M은 Binomial(N, M/N)과 같다. 서울 기준 비율은 고정(동 하나의 재추출 영향은 무시할 만함).
- RG: 동·기간별로 매칭 묶음을 복원추출해 g 중위값을 다시 구함.
반복 B_BOOT회, 구간은 백분위 5%·95%.

입력: data/processed/indicator_lq.csv, indicator_rg.csv, data/interim/rg_cells.parquet
출력: data/processed/indicator_ci.csv, outputs/tables/ci_summary.csv, ci_top_bottom.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

B_BOOT = 1000
SEED = 20261102
OUT = config.OUT_TAB


def boot_dlq(lq: pd.DataFrame, v: str, rng) -> pd.DataFrame:
    s = {p: lq[f"M_{p}_{v}"].sum() / lq[f"N_{p}_{v}"].sum() for p in ["pre", "post"]}  # 서울 기준 비율
    d = lq[lq[f"ok_{v}"]]
    lo, hi = [], []
    for _, r in d.iterrows():
        lqs = {}
        for p in ["pre", "post"]:
            n, m = int(r[f"N_{p}_{v}"]), int(r[f"M_{p}_{v}"])
            lqs[p] = rng.binomial(n, m / n, B_BOOT) / n / s[p]
        x = lqs["post"] - lqs["pre"]
        lo.append(np.percentile(x, 5))
        hi.append(np.percentile(x, 95))
    return pd.DataFrame({"adm_cd": d["adm_cd"], f"dLQ_{v}": d[f"dLQ_{v}"], f"dLQ_{v}_lo": lo, f"dLQ_{v}_hi": hi})


def boot_rg(rg: pd.DataFrame, cells: pd.DataFrame, rng) -> pd.DataFrame:
    d = rg[rg["ok"]]
    by = {k: g["g"].to_numpy() for k, g in cells.groupby(["adm_cd", "period"])}
    lo, hi = [], []
    for a in d["adm_cd"]:
        med = {}
        for p in ["pre", "post"]:
            g = by[(a, p)]
            med[p] = np.median(g[rng.integers(0, len(g), (B_BOOT, len(g)))], axis=1)
        x = med["post"] - med["pre"]
        lo.append(np.percentile(x, 5))
        hi.append(np.percentile(x, 95))
    return pd.DataFrame({"adm_cd": d["adm_cd"], "RG": d["RG"], "RG_lo": lo, "RG_hi": hi})


def main() -> None:
    rng = np.random.default_rng(SEED)
    lq = pd.read_csv(config.DATA_PROCESSED / "indicator_lq.csv", dtype={"adm_cd": str})
    rg = pd.read_csv(config.DATA_PROCESSED / "indicator_rg.csv", dtype={"adm_cd": str})
    cells = pd.read_parquet(config.DATA_INTERIM / "rg_cells.parquet")

    base = lq[["adm_cd", "adm_gu", "dong", "hold"]]
    ci = (base.merge(boot_dlq(lq, "all", rng), on="adm_cd", how="left")
              .merge(boot_dlq(lq, "exist", rng), on="adm_cd", how="left")
              .merge(boot_rg(rg, cells, rng), on="adm_cd", how="left"))
    for k in ["dLQ_all", "dLQ_exist", "RG"]:
        # 90% 구간이 0을 포함하지 않음 (값이 없는 동은 빈 값)
        ci[f"{k}_sig"] = ((ci[f"{k}_lo"] > 0) | (ci[f"{k}_hi"] < 0)).astype("boolean")
        ci.loc[ci[k].isna(), f"{k}_sig"] = pd.NA
    ci.to_csv(config.DATA_PROCESSED / "indicator_ci.csv", index=False, encoding="utf-8-sig")

    summ, tb = [], []
    for k in ["dLQ_all", "dLQ_exist", "RG"]:
        d = ci[ci[k].notna()]
        sig = d[d[f"{k}_sig"].astype(bool)]
        w = d[f"{k}_hi"] - d[f"{k}_lo"]
        summ.append({"지표": k, "값 있는 동": len(d), "구간이 0 제외": len(sig),
                     "  그중 양(+)": int((sig[k] > 0).sum()), "  그중 음(−)": int((sig[k] < 0).sum()),
                     "구간 폭 중위": w.median(), "구간 폭 90%": w.quantile(.9)})
        s2 = sig[~sig["hold"].astype(bool)]
        cols = ["adm_gu", "dong", k, f"{k}_lo", f"{k}_hi"]
        for side, part in [("상위", s2.nlargest(10, k)), ("하위", s2.nsmallest(10, k))]:
            tb.append(part[cols].rename(columns={k: "값", f"{k}_lo": "lo", f"{k}_hi": "hi"})
                      .assign(지표=k, 구분=side, 순위=range(1, len(part) + 1)))
            print(f"\n[{k} {side} 10] 90% 구간이 0을 포함하지 않는 동 중 (해석 유보 제외)")
            print(part[cols].round(3).to_string(index=False))
    # 자치구 단위 RG: 묶음을 자치구로 모아 중위값, 묶음 부트스트랩
    gu_of = rg.set_index("adm_cd")["adm_gu"]
    cg = cells.assign(gu=cells["adm_cd"].map(gu_of))
    gu_rows = []
    for gu, part in cg.groupby("gu"):
        arr = {p: part.loc[part["period"] == p, "g"].to_numpy() for p in ["pre", "post"]}
        med = {p: np.median(a[rng.integers(0, len(a), (B_BOOT, len(a)))], axis=1) for p, a in arr.items()}
        x = med["post"] - med["pre"]
        rgv = np.median(arr["post"]) - np.median(arr["pre"])
        lo_, hi_ = np.percentile(x, [5, 95])
        gu_rows.append({"자치구": gu, "묶음_pre": len(arr["pre"]), "묶음_post": len(arr["post"]),
                        "g_pre": np.median(arr["pre"]), "g_post": np.median(arr["post"]),
                        "RG": rgv, "RG_lo": lo_, "RG_hi": hi_, "구간이 0 제외": bool(lo_ > 0 or hi_ < 0)})
    gu_tab = pd.DataFrame(gu_rows).sort_values("RG", ascending=False)
    hold_gu = set(rg.loc[rg["adm_cd"].isin(list(config.HOLD_ADMDONG)), "adm_gu"])
    gu_tab["비고"] = np.where(gu_tab["자치구"].isin(hold_gu), "해석 유보 동 포함(잠원동·반포3동)", "")
    gu_tab = gu_tab[["자치구", "묶음_pre", "묶음_post", "g_pre", "g_post", "RG", "RG_lo", "RG_hi", "구간이 0 제외", "비고"]]
    gu_tab.to_csv(OUT / "rg_gu_ci.csv", index=False, encoding="utf-8-sig")
    print("\n[자치구 RG]\n" + gu_tab.round(4).to_string(index=False))
    # 평균으로의 회귀 점검: g_pre와 RG의 상관
    dd = rg[rg["ok"]]
    print(f"g_pre–RG 상관: 행정동 Pearson {dd['g_pre'].corr(dd['RG']):.3f} (n={len(dd)}), "
          f"자치구 Pearson {gu_tab['g_pre'].corr(gu_tab['RG']):.3f} (n={len(gu_tab)})")
    print(f"g_pre–g_post 상관: 행정동 {dd['g_pre'].corr(dd['g_post']):.3f}, 자치구 {gu_tab['g_pre'].corr(gu_tab['g_post']):.3f}")

    summ = pd.DataFrame(summ)
    summ.to_csv(OUT / "ci_summary.csv", index=False, encoding="utf-8-sig")
    pd.concat(tb).to_csv(OUT / "ci_top_bottom.csv", index=False, encoding="utf-8-sig")
    print("\n" + summ.round(3).to_string(index=False))


if __name__ == "__main__":
    main()

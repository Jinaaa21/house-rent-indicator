"""05. 지표 A: 월세계약 입지계수(LQ)와 변화(ΔLQ) (analysis_plan.md 3.1, 5.5의 ③).

LQ_i,t = (M_i,t / N_i,t) / (M_서울,t / N_서울,t),  ΔLQ_i = LQ_i,후 − LQ_i,전
서울 기준 비율은 각 버전과 같은 범위의 계약으로 구한다.

버전
  all            전체 계약 (기본, dLQ_all)
  exist          준공연도 ≤ EXIST_MAX_BUILD_YEAR 단지만 (dLQ_exist)
  all_nosmall    전체에서 전용면적 < SMALL_AREA 제외 (민감도 ③)
  exist_nosmall  exist에서 전용면적 < SMALL_AREA 제외 (민감도 ③)

입력: data/interim/rent_admdong.parquet, outputs/tables/admdong_counts.csv(전체 동 목록)
출력: data/processed/indicator_lq.csv
      outputs/tables/lq_summary.csv, lq_top_bottom.csv, lq_all_vs_exist.csv, lq_small_sensitivity.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OUT = config.OUT_TAB


def lq_table(rent: pd.DataFrame, v: str) -> pd.DataFrame:
    r = rent.assign(M=rent["rent_type"].eq("월세 포함"))
    g = r.groupby(["adm_cd", "period"]).agg(N=("M", "size"), M=("M", "sum")).unstack("period", fill_value=0)
    g.columns = [f"{a}_{p}_{v}" for a, p in g.columns]
    seoul = r.groupby("period")["M"].mean()
    for p in ["pre", "post"]:
        g[f"LQ_{p}_{v}"] = g[f"M_{p}_{v}"] / g[f"N_{p}_{v}"].replace(0, np.nan) / seoul[p]
    g[f"dLQ_{v}"] = g[f"LQ_post_{v}"] - g[f"LQ_pre_{v}"]
    g[f"ok_{v}"] = (g[f"N_pre_{v}"] >= config.MIN_N_LQ) & (g[f"N_post_{v}"] >= config.MIN_N_LQ)
    return g


def status(ok: pd.Series, hold: pd.Series) -> pd.Series:
    return np.select([~ok, hold], ["자료 부족", "해석 유보"], "정상")


def main() -> None:
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    rent = rent[~rent["invalid_rent"]]
    incl = rent  # 공공임대 포함(민감도)
    if config.EXCLUDE_PUBLIC_RENTAL:
        rent = rent[~rent["public_rental"]]
    exist = rent["build_year"] <= config.EXIST_MAX_BUILD_YEAR
    small = rent["area"] < config.SMALL_AREA
    subsets = {"all": rent, "exist": rent[exist], "all_nosmall": rent[~small], "exist_nosmall": rent[exist & ~small],
               "all_incl": incl, "exist_incl": incl[incl["build_year"] <= config.EXIST_MAX_BUILD_YEAR]}

    dong = pd.read_csv(OUT / "admdong_counts.csv", dtype={"adm_cd": str, "adm_cd2": str})
    out = dong[["adm_cd", "adm_cd2", "adm_gu", "adm_nm"]].set_index("adm_cd")
    for v, d in subsets.items():
        out = out.join(lq_table(d, v))
    for v in subsets:
        out[f"ok_{v}"] = out[f"ok_{v}"].fillna(False).astype(bool)
    out["hold"] = out.index.isin(list(config.HOLD_ADMDONG))
    out["status_all"] = status(out["ok_all"], out["hold"])
    out["status_exist"] = status(out["ok_exist"], out["hold"])
    out["dong"] = out["adm_nm"].str.split().str[-1]
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out.reset_index().to_csv(config.DATA_PROCESSED / "indicator_lq.csv", index=False, encoding="utf-8-sig")

    # ── 요약 ─────────────────────────────────────────
    summ = []
    for v in ["all", "exist"]:
        ok = out[out[f"ok_{v}"]]
        s = ok[f"dLQ_{v}"].describe(percentiles=[.1, .25, .5, .75, .9])
        summ.append({"버전": f"dLQ_{v}", "동 수(값 있음)": int(s["count"]),
                     "자료 부족": int((~out[f"ok_{v}"]).sum()), "해석 유보": int((ok["hold"]).sum()),
                     **{k: s[k] for k in ["mean", "std", "min", "10%", "25%", "50%", "75%", "90%", "max"]},
                     "ΔLQ>0 동 수": int((ok[f"dLQ_{v}"] > 0).sum())})
    summ = pd.DataFrame(summ)
    summ.to_csv(OUT / "lq_summary.csv", index=False, encoding="utf-8-sig")
    print(summ.round(3).to_string(index=False))

    cols = ["adm_gu", "dong", "N_pre_all", "N_post_all", "LQ_pre_all", "LQ_post_all", "dLQ_all", "dLQ_exist"]
    tb = []
    for v in ["all", "exist"]:
        ok = out[out[f"ok_{v}"] & ~out["hold"]]
        for side, part in [("상위", ok.nlargest(10, f"dLQ_{v}")), ("하위", ok.nsmallest(10, f"dLQ_{v}"))]:
            tb.append(part[cols].assign(기준=f"dLQ_{v}", 구분=side, 순위=range(1, 11)))
            print(f"\n[dLQ_{v} {side} 10] (해석 유보 동 제외)")
            print(part[cols].round(3).to_string(index=False))
    pd.concat(tb).to_csv(OUT / "lq_top_bottom.csv", index=False, encoding="utf-8-sig")

    # ── all vs exist ────────────────────────────────
    both = out[out["ok_all"] & out["ok_exist"] & ~out["hold"]].copy()
    both["diff"] = both["dLQ_exist"] - both["dLQ_all"]
    r_p = both["dLQ_all"].corr(both["dLQ_exist"])
    r_s = both["dLQ_all"].rank().corr(both["dLQ_exist"].rank())
    share_new = 1 - out["N_post_exist"] / out["N_post_all"]
    both["시행 후 신규(2018+) 비중"] = share_new.reindex(both.index)
    print(f"\n[dLQ_all vs dLQ_exist] 동 {len(both)}개, Pearson {r_p:.3f}, Spearman {r_s:.3f}")
    dcols = ["adm_gu", "dong", "dLQ_all", "dLQ_exist", "diff", "시행 후 신규(2018+) 비중"]
    ax = pd.concat([both.nlargest(10, "diff").assign(구분="exist가 더 큼"),
                    both.nsmallest(10, "diff").assign(구분="exist가 더 작음")])
    ax[dcols + ["구분"]].to_csv(OUT / "lq_all_vs_exist.csv", index=False, encoding="utf-8-sig")
    print(ax[dcols + ["구분"]].round(3).to_string(index=False))

    # ── 민감도 ③: 20㎡ 미만 제외 ─────────────────────
    sens = []
    for v in ["all", "exist"]:
        b = out[out[f"ok_{v}"] & out[f"ok_{v}_nosmall"] & ~out["hold"]].copy()
        b["diff"] = b[f"dLQ_{v}_nosmall"] - b[f"dLQ_{v}"]
        rp = b[f"dLQ_{v}"].corr(b[f"dLQ_{v}_nosmall"])
        rs = b[f"dLQ_{v}"].rank().corr(b[f"dLQ_{v}_nosmall"].rank())
        top = b.reindex(b["diff"].abs().sort_values(ascending=False).index).head(10)
        print(f"\n[③ {v}] 동 {len(b)}개, Pearson {rp:.3f}, Spearman {rs:.3f}, |차이| 중위 {b['diff'].abs().median():.3f}")
        print(top[["adm_gu", "dong", f"dLQ_{v}", f"dLQ_{v}_nosmall", "diff"]].round(3).to_string(index=False))
        sens.append(top[["adm_gu", "dong", f"dLQ_{v}", f"dLQ_{v}_nosmall", "diff"]]
                    .rename(columns={f"dLQ_{v}": "dLQ", f"dLQ_{v}_nosmall": "dLQ_nosmall"})
                    .assign(버전=v, 동수=len(b), Pearson=rp, Spearman=rs))
    pd.concat(sens).to_csv(OUT / "lq_small_sensitivity.csv", index=False, encoding="utf-8-sig")

    # ── 민감도: 공공임대 포함 ─────────────────────────
    pub = []
    for v in ["all", "exist"]:
        b = out[out[f"ok_{v}"] & out[f"ok_{v}_incl"] & ~out["hold"]].copy()
        b["diff"] = b[f"dLQ_{v}_incl"] - b[f"dLQ_{v}"]
        rp = b[f"dLQ_{v}"].corr(b[f"dLQ_{v}_incl"])
        rs = b[f"dLQ_{v}"].rank().corr(b[f"dLQ_{v}_incl"].rank())
        top = b.reindex(b["diff"].abs().sort_values(ascending=False).index).head(10)
        print(f"\n[공공임대 포함 {v}] 동 {len(b)}개, Pearson {rp:.3f}, Spearman {rs:.3f}")
        print(top[["adm_gu", "dong", f"dLQ_{v}", f"dLQ_{v}_incl", "diff"]].round(3).to_string(index=False))
        pub.append(top[["adm_gu", "dong", f"dLQ_{v}", f"dLQ_{v}_incl", "diff"]]
                   .rename(columns={f"dLQ_{v}": "기본(제외)", f"dLQ_{v}_incl": "공공임대 포함"})
                   .assign(버전=v, 동수=len(b), Pearson=rp, Spearman=rs))
    pd.concat(pub).to_csv(OUT / "lq_public_sensitivity.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()

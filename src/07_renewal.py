"""07. 참고 지표: 갱신요구권 사용률 (analysis_plan.md 3.3). 시행 후 기간만.

U_i   = '사용' 계약 수 / 갱신 계약 수            (갱신 계약의 useRRRight 빈 값 = 미사용으로 가정)
REN_i = 갱신 계약 수 / 계약구분이 확인된 계약 수
계약구분 빈 값 비율도 행정동별로 함께 산출. U의 90% 구간은 Wilson 구간.
공공임대 표시 단지는 제외(EXCLUDE_PUBLIC_RENTAL).

빈 값 가정 점검: 갱신 계약의 보증금 인상률(deposit / pre_deposit − 1)을 '사용'과 '빈 값'으로 나눠 비교.
  월세 포함 계약은 따로, 그중 월세가 종전과 같은 계약도 따로 표시. pre_deposit이 0이거나 빈 계약은 제외하고 건수 기록.
g = 0 점검: 시행 후 기간 매칭 묶음(rg_cells.parquet)에서 g = 0 / g ≠ 0 묶음의 갱신계약 비중 비교.

입력: data/interim/rent_admdong.parquet, rg_cells.parquet, outputs/tables/admdong_counts.csv
출력: data/processed/indicator_renewal.csv
      outputs/tables/renewal_summary.csv, renewal_top_bottom.csv, renewal_increase_compare.csv,
      renewal_g0_compare.csv, outputs/figures/07_increase_used_vs_blank.png
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C_USED, C_BLANK = "#2a78d6", "#eb6834"
OUT = config.OUT_TAB
Z90 = 1.6449


def wilson(k: pd.Series, n: pd.Series, z: float = Z90) -> tuple[pd.Series, pd.Series]:
    p = k / n
    den = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / den
    return c - h, c + h


CAP_TOL = 0.0005  # 만 원 단위 반올림 허용폭: 4.95~5.05%는 '5%'로 봄


def inc_stats(s: pd.Series) -> dict:
    return {"건수": len(s), "중위 인상률(%)": s.median() * 100, "25%(%)": s.quantile(.25) * 100,
            "75%(%)": s.quantile(.75) * 100, "5% 초과 비율(%)": (s > 0.05 + CAP_TOL).mean() * 100,
            "5%(±0.05%p) 비율(%)": ((s - 0.05).abs() <= CAP_TOL).mean() * 100,
            "0% 비율(%)": (s == 0).mean() * 100, "인하 비율(%)": (s < 0).mean() * 100}


def main() -> None:
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    d = rent[(rent["period"] == "post") & ~rent["invalid_rent"]]
    if config.EXCLUDE_PUBLIC_RENTAL:
        d = d[~d["public_rental"]]
    ct, rr = d["contractType"].fillna(""), d["useRRRight"].fillna("")
    d = d.assign(is_new=ct.eq("신규"), is_renew=ct.eq("갱신"), is_blank=ct.eq(""),
                 used=ct.eq("갱신") & rr.eq("사용"))
    n_odd = int((ct.eq("신규") & rr.eq("사용")).sum())
    # U_upper용: 갱신·빈 값 중 보증금 인상률이 정확히 5%(±0.05%p)인 계약을 '사용 표시 누락 가능'으로 봄
    inc_all = (d["deposit"] / d["pre_deposit"].where(d["pre_deposit"] > 0) - 1)
    d["blank5"] = d["is_renew"] & ~d["used"] & ((inc_all - 0.05).abs() <= CAP_TOL)

    # ── 1·2. 행정동별 U, U_upper, REN, 빈 값 비율 ──────
    g = d.groupby("adm_cd").agg(N=("is_new", "size"), n_new=("is_new", "sum"), n_renew=("is_renew", "sum"),
                                n_blank_type=("is_blank", "sum"), n_used=("used", "sum"), n_blank5=("blank5", "sum"))
    dong = pd.read_csv(OUT / "admdong_counts.csv", dtype={"adm_cd": str, "adm_cd2": str})
    out = dong[["adm_cd", "adm_cd2", "adm_gu", "adm_nm"]].set_index("adm_cd").join(g).fillna(0)
    for c in ["N", "n_new", "n_renew", "n_blank_type", "n_used", "n_blank5"]:
        out[c] = out[c].astype(int)
    out["U_upper"] = (out["n_used"] + out["n_blank5"]) / out["n_renew"].replace(0, np.nan)
    out["blank_type_share"] = out["n_blank_type"] / out["N"].replace(0, np.nan)
    out["REN"] = out["n_renew"] / (out["n_new"] + out["n_renew"]).replace(0, np.nan)
    out["U"] = out["n_used"] / out["n_renew"].replace(0, np.nan)
    out["U_lo"], out["U_hi"] = wilson(out["n_used"], out["n_renew"].replace(0, np.nan))
    out["ok"] = out["n_renew"] >= config.MIN_N_RENEW
    out["hold"] = out.index.isin(list(config.HOLD_ADMDONG))
    out["status"] = np.select([~out["ok"], out["hold"]], ["자료 부족", "해석 유보"], "정상")
    out["dong"] = out["adm_nm"].str.split().str[-1]
    out.reset_index().to_csv(config.DATA_PROCESSED / "indicator_renewal.csv", index=False, encoding="utf-8-sig")

    tot = d[["is_new", "is_renew", "is_blank", "used"]].sum()
    print(f"시행 후 계약 {len(d):,}건: 신규 {tot.is_new:,}, 갱신 {tot.is_renew:,}, 계약구분 빈 값 {tot.is_blank:,} "
          f"({tot.is_blank / len(d) * 100:.1f}%), 사용 {tot.used:,}. 신규인데 '사용' {n_odd}건(U 계산에서 제외)")
    print(f"서울 U = {tot.used / tot.is_renew * 100:.1f}%, REN = {tot.is_renew / (tot.is_new + tot.is_renew) * 100:.1f}%")
    ok = out[out["ok"]]
    rows = []
    for c in ["U", "REN", "blank_type_share"]:
        s = ok[c].describe(percentiles=[.1, .25, .5, .75, .9])
        rows.append({"항목": c, **{k: s[k] for k in ["count", "mean", "std", "min", "10%", "25%", "50%", "75%",
                                                      "90%", "max"]}})
    summ = pd.DataFrame(rows)
    summ.to_csv(OUT / "renewal_summary.csv", index=False, encoding="utf-8-sig")
    print(f"갱신 계약 ≥ {config.MIN_N_RENEW}인 동 {len(ok)}개, 자료 부족 {int((~out['ok']).sum())}개, "
          f"Wilson 90% 구간 폭 중위 {(ok['U_hi'] - ok['U_lo']).median() * 100:.1f}%p")
    print(summ.round(3).to_string(index=False))
    print(f"계약구분 빈 값 비율과 U의 상관(동): {ok['blank_type_share'].corr(ok['U']):.3f}")

    # U vs U_upper (실제 사용률은 U와 U_upper 사이)
    uu = ok[~ok["hold"]].copy()
    uu["rank_U"] = uu["U"].rank(ascending=False, method="min").astype(int)
    uu["rank_U_upper"] = uu["U_upper"].rank(ascending=False, method="min").astype(int)
    uu["rank_change"] = uu["rank_U_upper"] - uu["rank_U"]
    print(f"\n서울 U_upper = {(tot.used + d['blank5'].sum()) / tot.is_renew * 100:.1f}% "
          f"(빈 값 중 5% 계약 {int(d['blank5'].sum()):,}건)")
    print(f"U–U_upper 동별 Pearson {uu['U'].corr(uu['U_upper']):.3f}, "
          f"Spearman {uu['U'].rank().corr(uu['U_upper'].rank()):.3f}, 차이(U_upper−U) 중위 "
          f"{(uu['U_upper'] - uu['U']).median() * 100:.1f}%p, 최대 {(uu['U_upper'] - uu['U']).max() * 100:.1f}%p")
    rc = uu.reindex(uu["rank_change"].abs().sort_values(ascending=False).index).head(10)
    rcols = ["adm_gu", "dong", "n_renew", "U", "U_upper", "rank_U", "rank_U_upper", "rank_change"]
    rc[rcols].to_csv(OUT / "renewal_U_upper_rank_change.csv", index=False, encoding="utf-8-sig")
    print(rc[rcols].round(3).to_string(index=False))

    cols = ["adm_gu", "dong", "n_renew", "n_used", "U", "U_lo", "U_hi", "REN", "blank_type_share"]
    ok2 = ok[~ok["hold"]]
    tb = []
    for side, part in [("상위", ok2.nlargest(10, "U")), ("하위", ok2.nsmallest(10, "U"))]:
        tb.append(part[cols].assign(구분=side))
        print(f"\n[U {side} 10]")
        print(part[cols].round(3).to_string(index=False))
    pd.concat(tb).to_csv(OUT / "renewal_top_bottom.csv", index=False, encoding="utf-8-sig")

    # ── 3. 빈 값 가정 점검: 갱신 계약의 보증금 인상률 ────
    r = d[d["is_renew"]].copy()
    n_pre_na, n_pre_0 = int(r["pre_deposit"].isna().sum()), int((r["pre_deposit"] == 0).sum())
    r = r[r["pre_deposit"] > 0]
    r["inc"] = r["deposit"] / r["pre_deposit"] - 1
    r["grp"] = np.where(r["used"], "사용", "빈 값")
    r["rent_grp"] = np.where(r["rent_type"].eq("순수전세"), "순수전세",
                             np.where(r["monthly_rent"].eq(r["pre_monthly_rent"]), "월세 포함(월세 종전과 같음)",
                                      "월세 포함(월세 변동)"))
    print(f"\n갱신 계약 {int(d['is_renew'].sum()):,}건 중 pre_deposit 빈 값 {n_pre_na}건, 0 {n_pre_0}건 → 제외")
    cmp_rows = []
    for rg_ in ["순수전세", "월세 포함(월세 종전과 같음)", "월세 포함(월세 변동)"]:
        for grp in ["사용", "빈 값"]:
            s = r.loc[(r["rent_grp"] == rg_) & (r["grp"] == grp), "inc"]
            cmp_rows.append({"계약 유형": rg_, "갱신요구권": grp, **inc_stats(s)})
    cmp_ = pd.DataFrame(cmp_rows)
    cmp_ = pd.concat([cmp_, pd.DataFrame([{"계약 유형": f"pre_deposit 빈 값 {n_pre_na}건, 0 {n_pre_0}건 제외"}])])
    cmp_.to_csv(OUT / "renewal_increase_compare.csv", index=False, encoding="utf-8-sig")
    print(cmp_.round(2).to_string(index=False))

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), dpi=150, sharey=False)
    bins = np.arange(-0.205, 0.41, 0.01)  # 0%·5%가 구간 가운데 오도록 반 칸 이동
    for ax, (title, mask) in zip(axes, [("순수전세 갱신 계약", r["rent_grp"].eq("순수전세")),
                                        ("월세 포함 갱신 계약(월세 종전과 같음)",
                                         r["rent_grp"].eq("월세 포함(월세 종전과 같음)"))]):
        for grp, col in [("사용", C_USED), ("빈 값", C_BLANK)]:
            s = r.loc[mask & r["grp"].eq(grp), "inc"].clip(bins[0], bins[-1])
            ax.hist(s, bins=bins, density=True, histtype="step", lw=2, color=col,
                    label=f"{grp} (n={len(s):,}, 중위 {s.median() * 100:.1f}%)")
        # '사용'인데 5% 초과: 같은 밀도 기준(사용 전체 대비)으로 채워 따로 표시. 원인 [확인 필요]
        su = r.loc[mask & r["grp"].eq("사용"), "inc"]
        over = su[su > 0.05 + CAP_TOL].clip(bins[0], bins[-1])
        ax.hist(over, bins=bins, weights=np.full(len(over), 1 / (len(su) * 0.01)), color=C_USED, alpha=0.35,
                lw=0, label=f"사용 중 5% 초과 ({len(over) / len(su) * 100:.1f}%, 원인 확인 필요)")
        ax.axvline(0.05, color=INK2, lw=1, ls="--")
        ax.text(0.058, ax.get_ylim()[1] * 0.97, "5%", color=INK2, fontsize=8, va="top")
        ax.set_title(title, loc="left", fontsize=10, color=INK)
        ax.set_xlabel("보증금 인상률 (deposit / preDeposit − 1, 양끝 값은 끝 구간에 합침)".replace("−", "-"),
                      fontsize=8, color=INK)
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
        ax.legend(fontsize=8, frameon=False)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=8)
    axes[0].set_ylabel("밀도", fontsize=9, color=INK)
    fig.suptitle("갱신 계약의 보증금 인상률: 갱신요구권 '사용' 대 '빈 값' (시행 후 기간, 공공임대 제외)",
                 x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(config.OUT_FIG / "07_increase_used_vs_blank.png")
    print("그림 저장: outputs/figures/07_increase_used_vs_blank.png")

    # ── 4. g = 0 묶음의 갱신계약 비중 (시행 후) ─────────
    cells = pd.read_parquet(config.DATA_INTERIM / "rg_cells.parquet")
    cells = cells[cells["period"] == "post"].assign(g0=lambda x: x["g"] == 0)
    k = d[d["rent_type"].eq("순수전세") & ~d["trim_out"] & (d["build_year"] <= config.RG_MAX_BUILD_YEAR["post"])]
    k = k.merge(cells[["adm_cd", "aptSeq", "area_r", "g0"]], on=["adm_cd", "aptSeq", "area_r"])
    g0_rows = []
    for yr in [1, 2, "전체"]:
        kk = k if yr == "전체" else k[k["year_in_period"] == yr]
        for flag, lab in [(True, "g = 0 묶음"), (False, "g ≠ 0 묶음")]:
            x = kk[kk["g0"] == flag]
            known = x["is_new"].sum() + x["is_renew"].sum()
            g0_rows.append({"연차": yr, "묶음": lab, "묶음 수": int(cells["g0"].eq(flag).sum()), "계약": len(x),
                            "갱신 비중(%, 계약구분 확인분)": x["is_renew"].sum() / known * 100,
                            "계약구분 빈 값(%)": x["is_blank"].mean() * 100,
                            "갱신 중 사용(%)": x["used"].sum() / max(x["is_renew"].sum(), 1) * 100})
    g0c = pd.DataFrame(g0_rows)
    g0c.to_csv(OUT / "renewal_g0_compare.csv", index=False, encoding="utf-8-sig")
    print("\n" + g0c.round(2).to_string(index=False))


if __name__ == "__main__":
    main()

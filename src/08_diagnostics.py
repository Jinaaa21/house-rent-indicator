"""08. 신고제 단절 진단 (CLAUDE.md 4.3) + 중복 행 강건성 점검 (4.4).

- 서울 전체: 기간별 계약 수, 월세 포함 비중
- 행정동별 신고 증가배수 R_i = (N_i,후 / N_i,전) / (N_서울,후 / N_서울,전)
- R_i와 ΔLQ_i의 상관(Pearson, Spearman)과 산점도
- 4.4: 완전 중복을 하나만 남긴 자료로 R과 ΔLQ를 다시 계산해 비교

ΔLQ는 지표 A(05)와 같은 정의로 여기서 계산한다(05보다 먼저 진단하기 위함).
대상 동: 두 기간 모두 N ≥ MIN_N_LQ.

입력: data/interim/rent_admdong.parquet
출력: outputs/tables/diag_seoul_period.csv, diag_R_dLQ_admdong.csv, diag_dedup_robustness.csv
      outputs/figures/08_R_vs_dLQ.png
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
INK, INK2, GRID, MARK = "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6"


def dong_table(rent: pd.DataFrame) -> pd.DataFrame:
    r = rent[~rent["invalid_rent"]]
    g = (r.assign(M=r["rent_type"].eq("월세 포함"))
          .groupby(["adm_cd", "adm_gu", "adm_nm", "period"]).agg(N=("M", "size"), M=("M", "sum"))
          .unstack("period", fill_value=0))
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    seoul = r.groupby("period").agg(N=("rent_type", "size"),
                                     share=("rent_type", lambda s: (s == "월세 포함").mean()))
    for p in ["pre", "post"]:
        g[f"LQ_{p}"] = g[f"M_{p}"] / g[f"N_{p}"] / seoul.at[p, "share"]
    g["dLQ"] = g["LQ_post"] - g["LQ_pre"]
    g["R"] = (g["N_post"] / g["N_pre"]) / (seoul.at["post", "N"] / seoul.at["pre", "N"])
    g["ok"] = (g["N_pre"] >= config.MIN_N_LQ) & (g["N_post"] >= config.MIN_N_LQ)
    return g.reset_index()


def corr(df: pd.DataFrame) -> dict:
    d = df[df["ok"]]
    return {"n": len(d),
            "pearson_R_dLQ": d["R"].corr(d["dLQ"]),
            "spearman_R_dLQ": d["R"].rank().corr(d["dLQ"].rank()),  # 순위의 Pearson = Spearman
            "pearson_logR_dLQ": np.log(d["R"]).corr(d["dLQ"])}


def main() -> None:
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    rent = rent[~rent["invalid_rent"]]

    # 서울 전체 기간별
    s = (rent.groupby(["period", "year_in_period"])
             .agg(계약수=("rent_type", "size"), 월세포함=("rent_type", lambda x: (x == "월세 포함").sum())))
    tot = rent.groupby("period").agg(계약수=("rent_type", "size"),
                                     월세포함=("rent_type", lambda x: (x == "월세 포함").sum()))
    tot["year_in_period"] = "전체"
    s = pd.concat([s.reset_index(), tot.reset_index()], ignore_index=True)
    s["월세 포함 비중(%)"] = (s["월세포함"] / s["계약수"] * 100).round(2)
    s["period"] = s["period"].map({"pre": "시행 전", "post": "시행 후"})
    s = s.sort_values(["period", "year_in_period"], key=lambda c: c.astype(str), ascending=[False, True])
    s.to_csv(config.OUT_TAB / "diag_seoul_period.csv", index=False, encoding="utf-8-sig")
    print(s.to_string(index=False))

    base = dong_table(rent)
    base.to_csv(config.OUT_TAB / "diag_R_dLQ_admdong.csv", index=False, encoding="utf-8-sig")
    ok = base[base["ok"]]
    c0 = corr(base)
    print(f"\n대상 동 {c0['n']}개 / R 분포:")
    print(ok["R"].describe(percentiles=[.05, .25, .5, .75, .95]).round(3).to_string())
    print({k: round(v, 3) for k, v in c0.items()})

    # 4.4 중복 제거 강건성
    dd = dong_table(rent[~rent["dup_extra"]])
    m = base.merge(dd[["adm_cd", "R", "dLQ", "ok"]], on="adm_cd", suffixes=("", "_dedup"))
    m = m[m["ok"] & m["ok_dedup"]]
    c1 = corr(dd)
    rob = pd.DataFrame([
        {"항목": "대상 동 수", "기본": c0["n"], "중복 제거": c1["n"]},
        {"항목": "R–ΔLQ Pearson", "기본": c0["pearson_R_dLQ"], "중복 제거": c1["pearson_R_dLQ"]},
        {"항목": "R–ΔLQ Spearman", "기본": c0["spearman_R_dLQ"], "중복 제거": c1["spearman_R_dLQ"]},
        {"항목": "ΔLQ 기본–중복제거 상관", "기본": m["dLQ"].corr(m["dLQ_dedup"]), "중복 제거": np.nan},
        {"항목": "R 기본–중복제거 상관", "기본": m["R"].corr(m["R_dedup"]), "중복 제거": np.nan},
        {"항목": "|ΔLQ 차이| 최대", "기본": (m["dLQ"] - m["dLQ_dedup"]).abs().max(), "중복 제거": np.nan},
        {"항목": "|R 차이| 최대", "기본": (m["R"] - m["R_dedup"]).abs().max(), "중복 제거": np.nan},
    ])
    rob.to_csv(config.OUT_TAB / "diag_dedup_robustness.csv", index=False, encoding="utf-8-sig")
    print("\n" + rob.round(3).to_string(index=False))

    # 산점도: R(x, 로그축) – ΔLQ(y)
    fig, ax = plt.subplots(figsize=(7.5, 5.5), dpi=150)
    ax.scatter(ok["R"], ok["dLQ"], s=14, color=MARK, alpha=0.7, edgecolor="white", linewidth=0.5)
    ax.set_xscale("log")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.axvline(1, color=INK2, lw=0.8)
    ticks = [0.3, 0.5, 1, 2, 3, 5, 10]
    ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax.minorticks_off()
    lab = pd.concat([ok.nlargest(4, "R"), ok.nsmallest(1, "R"), ok.nlargest(3, "dLQ"), ok.nsmallest(3, "dLQ")])
    for _, r in lab.drop_duplicates("adm_cd").iterrows():
        ax.annotate(f"{r['adm_gu']} {r['adm_nm'].split()[-1]}", (r["R"], r["dLQ"]), fontsize=7, color=INK2,
                    xytext=(4, 3), textcoords="offset points")
    ax.set_xlabel("신고 증가배수 R (로그 축, 1 = 서울 평균)", color=INK)
    ax.set_ylabel("ΔLQ (시행 후 LQ - 시행 전 LQ)", color=INK)
    ax.set_title(f"행정동별 신고 증가배수와 월세계약 LQ 변화 (n = {c0['n']})", color=INK, loc="left", fontsize=11, pad=20)
    ax.text(0.0, 1.015, f"Pearson r = {c0['pearson_R_dLQ']:.2f}, Spearman ρ = {c0['spearman_R_dLQ']:.2f}"
            f" · 두 기간 모두 계약 {config.MIN_N_LQ}건 이상인 동", transform=ax.transAxes, fontsize=8, color=INK2)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    fig.tight_layout()
    config.OUT_FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(config.OUT_FIG / "08_R_vs_dLQ.png")
    print("그림 저장: outputs/figures/08_R_vs_dLQ.png")


if __name__ == "__main__":
    main()

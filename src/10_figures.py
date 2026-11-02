"""10. 지도·그래프 (CLAUDE.md 5.2·5.3).

지도 표시 규칙(5.2 확정): 색 = 값(발산형, 0 기준). 부트스트랩 90% 구간이 0을 포함하는 동은 같은 색을
불투명도 35%(흰 바탕과 섞은 색)로, 자료 부족은 중립 회색, 해석 유보는 빗금+굵은 테두리. 자치구 경계는 굵은 선.

출력(outputs/figures):
  10_map_dlq_exist_rg.png   ΔLQ(기존 단지)와 RG 나란히, 제목 아래 Moran's I
  10_map_dlq_all.png        ΔLQ(전체)
  10_map_u.png              갱신요구권 사용률 U
  10_scatter_dlq_rg.png     ΔLQ(기존 단지)–RG, 권역 색, 점 크기 = 계약 수
  10_scatter_u.png          U–RG, U–ΔLQ(기존 단지)
  10_box_region.png         권역별 ΔLQ(기존 단지)·RG 상자그림
  10_diag_monthly.png       신고제 월별 추이(08c 그림 복사)
  10_diag_R_dlq_exist.png   신고 증가배수 R–ΔLQ(준공 2017년 이하 단지)
  10_map_lisa.png           ΔLQ(기존 단지)·RG LISA 군집(FDR 기준), 0.05 기준 군집 수 병기
"""
import importlib
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, Normalize, to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
NODATA = "#bdbcb6"          # 자료 부족(중립 회색) — 발산형 중앙 회색(#f0efec)보다 진하게 구분
LIGHT_ALPHA = 0.35
DIV = LinearSegmentedColormap.from_list("div", ["#104281", "#3987e5", "#f0efec", "#e66767", "#a8201f"])
SEQ = LinearSegmentedColormap.from_list("seq", ["#e6f0fc", "#86b6ef", "#2a78d6", "#104281"])
REGION_COLOR = {"도심권": "#2a78d6", "동북권": "#eb6834", "서북권": "#1baf7a", "서남권": "#eda100", "동남권": "#6250d6"}
FIG = config.OUT_FIG


def style(ax):
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)


def light(rgba):
    """불투명도 35%를 흰 바탕과 섞은 색으로 (자치구 선이 비치지 않게)."""
    r = np.array(rgba)
    return tuple(LIGHT_ALPHA * r[:3] + (1 - LIGHT_ALPHA) * np.ones(3)) + (1.0,)


def load() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame]:
    g = gpd.read_file(config.ADMDONG_FILE)
    g = g[g["sidonm"] == "서울특별시"][["adm_cd", "geometry"]].to_crs(epsg=5179)
    rd = lambda f: pd.read_csv(config.DATA_PROCESSED / f, dtype={"adm_cd": str})
    lq, rg, rn, ci = rd("indicator_lq.csv"), rd("indicator_rg.csv"), rd("indicator_renewal.csv"), rd("indicator_ci.csv")
    df = (lq[["adm_cd", "adm_gu", "dong", "hold", "dLQ_all", "ok_all", "dLQ_exist", "ok_exist", "N_pre_all", "N_post_all"]]
          .merge(rg[["adm_cd", "RG", "ok"]].rename(columns={"ok": "ok_rg"}), on="adm_cd")
          .merge(rn[["adm_cd", "U", "U_lo", "U_hi", "U_upper", "ok"]].rename(columns={"ok": "ok_u"}), on="adm_cd")
          .merge(ci[["adm_cd", "dLQ_all_sig", "dLQ_exist_sig", "RG_sig"]], on="adm_cd"))
    for c in ["hold", "ok_all", "ok_exist", "ok_rg", "ok_u"]:
        df[c] = df[c].astype(bool)
    for c in ["dLQ_all_sig", "dLQ_exist_sig", "RG_sig"]:
        df[c] = df[c].map({True: True, False: False, "True": True, "False": False}).fillna(False).astype(bool)
    df["region"] = df["adm_gu"].map(config.GU_REGION)
    df["N_total"] = df["N_pre_all"] + df["N_post_all"]
    gdf = g.merge(df, on="adm_cd")
    gu = gdf.dissolve(by="adm_gu", as_index=False)[["adm_gu", "geometry"]]
    mor = pd.read_csv(config.OUT_TAB / "moran_global.csv")
    return gdf, gu, mor


def moran_text(mor: pd.DataFrame, col: str) -> str:
    q = mor[(mor["지표"] == col) & (mor["가중행렬"] == "퀸 인접")].iloc[0]
    k = mor[(mor["지표"] == col) & (mor["가중행렬"].str.startswith("k"))].iloc[0]
    p = lambda v: "p < 0.001" if v <= 0.001 else f"p = {v:.3f}"
    iq, ik, pq = q["Moran's I"], k["Moran's I"], q["p(순열, 999회)"]
    return f"Moran's I = {iq:.3f} (퀸 인접, {p(pq)}) · k=6: {ik:.3f}"


def draw_map(ax, gdf, gu, col, okc, sigc, title, sub, cmap=DIV, diverging=True, fmt="{:+.2f}"):
    valid = gdf[okc] & gdf[col].notna()
    v = gdf.loc[valid, col]
    if diverging:
        lim = float(np.nanpercentile(v.abs(), 97))
        norm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
    else:
        lo, hi = np.nanpercentile(v, [2, 98])
        norm = Normalize(vmin=lo, vmax=hi)
    colors = []
    for _, r in gdf.iterrows():
        if not (r[okc] and pd.notna(r[col])):
            colors.append(to_rgba(NODATA))
            continue
        c = cmap(norm(np.clip(r[col], norm.vmin, norm.vmax)))
        colors.append(c if (sigc is None or r[sigc]) else light(c))
    gdf.plot(ax=ax, color=colors, edgecolor="white", linewidth=0.25)
    hold = gdf[gdf["hold"]]
    hold.plot(ax=ax, facecolor="none", edgecolor=INK, linewidth=1.4, hatch="////")
    gu.boundary.plot(ax=ax, color=INK2, linewidth=0.8)
    ax.set_axis_off()
    ax.set_title(title, loc="left", fontsize=11.5, color=INK, pad=16)
    ax.text(0, 1.0, sub, transform=ax.transAxes, fontsize=8, color=INK2, va="bottom")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = plt.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.04, pad=0.02, aspect=35,
                      extend="both")
    cb.ax.tick_params(labelsize=7, colors=INK2)
    cb.outline.set_visible(False)
    cb.ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: fmt.format(x)))
    return norm


def map_legend(fig, with_sig=True, y=0.02, ncol=None):
    sample = DIV(0.85)
    items = []
    if with_sig:
        items += [Patch(facecolor=sample, edgecolor="none", label="90% 구간이 0을 포함하지 않음(진한 색)"),
                  Patch(facecolor=light(sample), edgecolor="none", label="90% 구간이 0을 포함(옅은 색)")]
    items += [Patch(facecolor=NODATA, edgecolor="none", label="자료 부족(최소 건수 미달)"),
              Patch(facecolor="white", edgecolor=INK, hatch="////", linewidth=1.2, label="해석 유보(잠원동·반포3동)"),
              Line2D([0], [0], color=INK2, lw=0.8, label="자치구 경계")]
    fig.legend(handles=items, loc="lower center", ncol=ncol or len(items), fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, y), handlelength=1.6)


def maps(gdf, gu, mor):
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.6), dpi=150)
    draw_map(axes[0], gdf, gu, "dLQ_exist", "ok_exist", "dLQ_exist_sig", "월세계약 LQ 변화 ΔLQ (준공 2017년 이하 단지)",
             moran_text(mor, "dLQ_exist"))
    draw_map(axes[1], gdf, gu, "RG", "ok_rg", "RG_sig", "상대 누적 상승률 RG (순수전세 ㎡당 보증금)",
             moran_text(mor, "RG"), fmt="{:+.3f}")
    fig.suptitle("임대차 2법 시행 전후 행정동별 변화: 2018.8.~2020.7. 대비 2022.8.~2024.7.", x=0.01, ha="left",
                 fontsize=12.5, color=INK)
    map_legend(fig)
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    fig.savefig(FIG / "10_map_dlq_exist_rg.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 6.8), dpi=150)
    draw_map(ax, gdf, gu, "dLQ_all", "ok_all", "dLQ_all_sig", "월세계약 LQ 변화 ΔLQ (전체 계약)", moran_text(mor, "dLQ_all"))
    map_legend(fig, y=0.0, ncol=3)
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    fig.savefig(FIG / "10_map_dlq_all.png")
    plt.close(fig)

    seoul_u = gdf.loc[gdf["ok_u"], "U"].median()
    fig, ax = plt.subplots(figsize=(7.5, 6.8), dpi=150)
    draw_map(ax, gdf, gu, "U", "ok_u", None, "갱신요구권 사용률 U (시행 후 기간, 참고 지표)",
             moran_text(mor, "U") + f" · 동 중위 {seoul_u:.2f}", cmap=SEQ, diverging=False, fmt="{:.2f}")
    map_legend(fig, with_sig=False, y=0.0, ncol=3)
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    fig.savefig(FIG / "10_map_u.png")
    plt.close(fig)


def size_of(n):
    return 6 + 150 * np.sqrt(n / 10000)


def scatters(gdf):
    df = pd.DataFrame(gdf.drop(columns="geometry"))
    d = df[df["ok_exist"] & df["ok_rg"] & ~df["hold"]]
    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    for reg, c in REGION_COLOR.items():
        s = d[d["region"] == reg]
        ax.scatter(s["dLQ_exist"], s["RG"], s=size_of(s["N_total"]), color=c, alpha=0.75, edgecolor="white",
                   linewidth=0.6, label=f"{reg} ({len(s)})")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.axvline(0, color=INK2, lw=0.8)
    r = d["dLQ_exist"].corr(d["RG"])
    rs = d["dLQ_exist"].rank().corr(d["RG"].rank())
    for (x, y, lab) in [(0.98, 0.98, "월세 쪽↑ · 상승 폭↑"), (0.02, 0.98, "월세 쪽↓ · 상승 폭↑"),
                        (0.02, 0.02, "월세 쪽↓ · 상승 폭↓"), (0.98, 0.02, "월세 쪽↑ · 상승 폭↓")]:
        ax.text(x, y, lab, transform=ax.transAxes, fontsize=7.5, color=INK2,
                ha="right" if x > 0.5 else "left", va="top" if y > 0.5 else "bottom")
    ax.set_xlabel("ΔLQ (준공 2017년 이하 단지)", color=INK)
    ax.set_ylabel("RG (로그 상승률 차이)", color=INK)
    ax.set_title("행정동별 ΔLQ와 RG", loc="left", fontsize=11.5, color=INK, pad=16)
    ax.text(0, 1.0, f"n = {len(d)}, Pearson r = {r:.2f}, Spearman ρ = {rs:.2f} · 점 크기 = 두 기간 계약 수 · "
            "자료 부족·해석 유보 제외", transform=ax.transAxes, fontsize=8, color=INK2, va="bottom")
    style(ax)
    leg1 = ax.legend(title="권역(동 수)", fontsize=8, title_fontsize=8, frameon=False, loc="upper left",
                     bbox_to_anchor=(1.0, 1.0))
    ax.add_artist(leg1)
    hs = [plt.scatter([], [], s=size_of(n), color="#bdbcb6", edgecolor="white") for n in [1000, 5000, 10000]]
    ax.legend(hs, ["1,000건", "5,000건", "10,000건"], title="계약 수", fontsize=8, title_fontsize=8, frameon=False,
              loc="lower left", bbox_to_anchor=(1.0, 0.0), labelspacing=1.2)
    fig.tight_layout()
    fig.savefig(FIG / "10_scatter_dlq_rg.png")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=150)
    for ax, (ycol, okc, ylab) in zip(axes, [("RG", "ok_rg", "RG"), ("dLQ_exist", "ok_exist", "ΔLQ (준공 2017년 이하 단지)")]):
        d = df[df["ok_u"] & df[okc] & ~df["hold"]]
        for reg, c in REGION_COLOR.items():
            s = d[d["region"] == reg]
            ax.scatter(s["U"], s[ycol], s=size_of(s["N_total"]), color=c, alpha=0.75, edgecolor="white",
                       linewidth=0.6, label=reg)
        ax.axhline(0, color=INK2, lw=0.8)
        ax.axvline(d["U"].median(), color=INK2, lw=0.8, ls="--")
        ax.text(d["U"].median(), ax.get_ylim()[1], " U 중위", fontsize=7.5, color=INK2, va="top")
        r = d["U"].corr(d[ycol])
        rs = d["U"].rank().corr(d[ycol].rank())
        ax.set_title(f"U와 {ylab.split(' ')[0]}", loc="left", fontsize=11, color=INK, pad=16)
        ax.text(0, 1.0, f"n = {len(d)}, Pearson r = {r:.2f}, Spearman ρ = {rs:.2f}", transform=ax.transAxes,
                fontsize=8, color=INK2, va="bottom")
        ax.set_xlabel("갱신요구권 사용률 U", color=INK)
        ax.set_ylabel(ylab, color=INK)
        style(ax)
    axes[1].legend(title="권역", fontsize=8, title_fontsize=8, frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    fig.savefig(FIG / "10_scatter_u.png")
    plt.close(fig)


def boxes(gdf):
    df = pd.DataFrame(gdf.drop(columns="geometry"))
    order = list(REGION_COLOR)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), dpi=150)
    rng = np.random.default_rng(1)
    for ax, (col, okc, lab) in zip(axes, [("dLQ_exist", "ok_exist", "ΔLQ (준공 2017년 이하 단지)"), ("RG", "ok_rg", "RG")]):
        d = df[df[okc] & ~df["hold"]]
        data = [d.loc[d["region"] == r, col].dropna() for r in order]
        bp = ax.boxplot(data, widths=0.5, patch_artist=True, showfliers=False,
                        medianprops={"color": INK, "lw": 1.5}, whiskerprops={"color": INK2},
                        capprops={"color": INK2}, boxprops={"edgecolor": INK2})
        for patch, r in zip(bp["boxes"], order):
            patch.set_facecolor(light(to_rgba(REGION_COLOR[r])))
        for i, (r, s) in enumerate(zip(order, data), 1):
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(s)), s, s=8, color=REGION_COLOR[r], alpha=0.6, linewidth=0)
        ax.set_xticks(range(1, len(order) + 1), [f"{r}\n(n={len(s)})" for r, s in zip(order, data)])
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_title(f"권역별 {lab}", loc="left", fontsize=11, color=INK)
        ax.set_ylabel(lab, color=INK)
        style(ax)
    fig.text(0.01, 0.01, "상자: 사분위 범위, 가운데 선: 중위값, 점: 행정동 (자료 부족·해석 유보 제외). 권역: 2030 서울생활권계획 권역 구분",
             fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(FIG / "10_box_region.png")
    plt.close(fig)


LISA_COLOR = {"HH": "#a8201f", "LL": "#104281", "HL": "#e66767", "LH": "#86b6ef", "유의하지 않음": "#f0efec"}


def lisa_map(gdf, gu):
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.6), dpi=150)
    for ax, (col, okc, title) in zip(axes, [("dLQ_exist", "ok_exist", "ΔLQ (준공 2017년 이하 단지)"),
                                            ("RG", "ok_rg", "RG")]):
        lt = pd.read_csv(config.OUT_TAB / f"lisa_{col}.csv", dtype={"adm_cd": str})
        m = gdf[["adm_cd", "hold", "geometry"]].merge(lt[["adm_cd", "cluster_fdr"]], on="adm_cd", how="left")
        colors = [LISA_COLOR[c] if isinstance(c, str) else NODATA for c in m["cluster_fdr"]]
        m.plot(ax=ax, color=colors, edgecolor="white", linewidth=0.25)
        m[m["hold"]].plot(ax=ax, facecolor="none", edgecolor=INK, linewidth=1.4, hatch="////")
        gu.boundary.plot(ax=ax, color=INK2, linewidth=0.8)
        ax.set_axis_off()
        n_fdr = (lt["cluster_fdr"] != "유의하지 않음").sum()
        c05 = lt["cluster_005"].value_counts()
        ax.set_title(f"LISA 군집: {title}", loc="left", fontsize=11.5, color=INK, pad=16)
        ax.text(0, 1.0, f"FDR 보정(0.05) 기준 유의 군집 {n_fdr}개 · 참고: p ≤ 0.05 기준 HH {c05.get('HH', 0)}, "
                f"LL {c05.get('LL', 0)}, HL {c05.get('HL', 0)}, LH {c05.get('LH', 0)} (표 lisa_{col}.csv)",
                transform=ax.transAxes, fontsize=8, color=INK2, va="bottom")
    items = [Patch(facecolor=LISA_COLOR[k], edgecolor="none", label=k) for k in ["HH", "LL", "HL", "LH"]]
    items += [Patch(facecolor=LISA_COLOR["유의하지 않음"], edgecolor="none", label="유의하지 않음"),
              Patch(facecolor=NODATA, edgecolor="none", label="자료 부족"),
              Patch(facecolor="white", edgecolor=INK, hatch="////", label="해석 유보")]
    fig.legend(handles=items, loc="lower center", ncol=len(items), fontsize=8, frameon=False, bbox_to_anchor=(0.5, 0.02))
    fig.suptitle("국지적 Moran(LISA) 군집: 퀸 인접, 순열 99,999회, FDR 보정", x=0.01, ha="left", fontsize=12.5, color=INK)
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    fig.savefig(FIG / "10_map_lisa.png")
    plt.close(fig)


def diagnostics():
    shutil.copy(FIG / "08c_monthly_trend.png", FIG / "10_diag_monthly.png")
    diag = importlib.import_module("08_diagnostics")
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    rent = rent[~rent["invalid_rent"] & (rent["build_year"] <= config.EXIST_MAX_BUILD_YEAR)]
    if config.EXCLUDE_PUBLIC_RENTAL:
        rent = rent[~rent["public_rental"]]
    t = diag.dong_table(rent)
    ok = t[t["ok"] & ~t["adm_cd"].isin(list(config.HOLD_ADMDONG))]
    r, rs = ok["R"].corr(ok["dLQ"]), ok["R"].rank().corr(ok["dLQ"].rank())
    fig, ax = plt.subplots(figsize=(7.5, 5.5), dpi=150)
    ax.scatter(ok["R"], ok["dLQ"], s=14, color="#2a78d6", alpha=0.7, edgecolor="white", linewidth=0.5)
    ax.set_xscale("log")
    ticks = [0.3, 0.5, 0.7, 1, 1.5, 2, 3]
    ax.set_xticks(ticks, [f"{x:g}" for x in ticks])
    ax.minorticks_off()
    ax.axhline(0, color=INK2, lw=0.8)
    ax.axvline(1, color=INK2, lw=0.8)
    ax.set_xlabel("신고 증가배수 R (로그 축, 1 = 서울 평균)", color=INK)
    ax.set_ylabel("ΔLQ (준공 2017년 이하 단지)", color=INK)
    ax.set_title(f"신고 증가배수와 ΔLQ: 기존 단지 기준 (n = {len(ok)})", loc="left", fontsize=11, color=INK, pad=20)
    ax.text(0, 1.015, f"Pearson r = {r:.2f}, Spearman ρ = {rs:.2f} · 준공 2017년 이하, 공공임대 제외, "
            "두 기간 모두 30건 이상", transform=ax.transAxes, fontsize=8, color=INK2)
    style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "10_diag_R_dlq_exist.png")
    plt.close(fig)


def main() -> None:
    gdf, gu, mor = load()
    maps(gdf, gu, mor)
    scatters(gdf)
    boxes(gdf)
    lisa_map(gdf, gu)
    diagnostics()
    print("저장:", sorted(p.name for p in FIG.glob("10_*.png")))


if __name__ == "__main__":
    main()

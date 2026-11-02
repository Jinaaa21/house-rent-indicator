"""08c. 신고제 단절 진단: 2018.8.~2024.7. 서울 월별 계약 수와 월세 포함 비중.

사이 기간(2020.8.~2022.7.) 파일까지 원자료에서 바로 집계한다. 진단 전용이며 지표 계산에는 쓰지 않는다.
신고제 시행(2021.6.1.) 직전 6개월과 직후 6개월의 월세 포함 비중 평균 차이를 계산한다.

입력: data/raw/apt_rent_*.csv (72개월)
출력: outputs/tables/diag_monthly_seoul.csv, diag_reporting_6m.csv
      outputs/figures/08c_monthly_trend.png
"""
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
INK, INK2, GRID, MARK, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6", "#f1f0ec"


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def main() -> None:
    start, end = config.PERIODS["pre"][0], config.PERIODS["post"][1]
    months = [p.strftime("%Y%m") for p in pd.period_range(start[:7], end[:7], freq="M")]
    rows, missing = [], []
    for ym in months:
        n = m = 0
        for lawd in config.SEOUL_GU:
            f = config.DATA_RAW / f"apt_rent_{lawd}_{ym}.csv"
            if not f.exists():
                missing.append(f.name)
                continue
            df = pd.read_csv(f, dtype=str, keep_default_na=False, usecols=["deposit", "monthlyRent"])
            dep, rent = to_num(df["deposit"]).fillna(0), to_num(df["monthlyRent"]).fillna(0)
            valid = ~((dep == 0) & (rent == 0))  # invalid_rent 제외 (02와 같은 기준)
            n += int(valid.sum())
            m += int((valid & (rent > 0)).sum())
        rows.append({"ym": ym, "계약수": n, "월세포함": m})
    if missing:
        sys.exit(f"원자료 파일 없음 {len(missing)}개 (예: {missing[:3]}). 01_collect.py로 먼저 받으세요.")

    t = pd.DataFrame(rows)
    t["month"] = pd.to_datetime(t["ym"], format="%Y%m")
    t["월세 포함 비중(%)"] = t["월세포함"] / t["계약수"] * 100
    t["구간"] = "사이(진단 전용)"
    for p, (s, e) in config.PERIODS.items():
        t.loc[t["month"].between(s[:7], e), "구간"] = {"pre": "시행 전", "post": "시행 후"}[p]
    t.drop(columns="month").to_csv(config.OUT_TAB / "diag_monthly_seoul.csv", index=False, encoding="utf-8-sig")

    # 신고제 직전·직후 6개월
    rep = pd.Timestamp(config.REPORTING_DATE)
    mo = pd.to_datetime(t["ym"], format="%Y%m")
    before = t[(mo >= rep - pd.DateOffset(months=6)) & (mo < rep)]
    after = t[(mo >= rep) & (mo < rep + pd.DateOffset(months=6))]
    six = pd.DataFrame([
        {"구간": f"직전 6개월({before['ym'].iloc[0]}~{before['ym'].iloc[-1]})",
         "월평균 계약수": before["계약수"].mean(), "월별 비중 평균(%)": before["월세 포함 비중(%)"].mean(),
         "합산 비중(%)": before["월세포함"].sum() / before["계약수"].sum() * 100},
        {"구간": f"직후 6개월({after['ym'].iloc[0]}~{after['ym'].iloc[-1]})",
         "월평균 계약수": after["계약수"].mean(), "월별 비중 평균(%)": after["월세 포함 비중(%)"].mean(),
         "합산 비중(%)": after["월세포함"].sum() / after["계약수"].sum() * 100},
    ])
    diff = six.iloc[1, 1:] - six.iloc[0, 1:]
    six = pd.concat([six, pd.DataFrame([{"구간": "차이(직후 - 직전)", **diff.to_dict()}])], ignore_index=True)
    six.to_csv(config.OUT_TAB / "diag_reporting_6m.csv", index=False, encoding="utf-8-sig")
    print(six.round(2).to_string(index=False))

    # 위약(placebo) 비교: 같은 달 구성(12~5월 대 6~11월)을 신고제가 없는 시점에 적용
    def window(a: str, b: str) -> pd.DataFrame:
        return t[(t["ym"] >= a) & (t["ym"] <= b)]

    comps = [("신고제 시점", "202012", "202105", "202106", "202111"),
             ("위약 1: 신고제 이전", "201912", "202005", "202006", "202011"),
             ("위약 2: 신고제 이후", "202212", "202305", "202306", "202311")]
    pl = []
    for name, a1, b1, a2, b2 in comps:
        w1, w2 = window(a1, b1), window(a2, b2)
        m1, m2 = w1["월세 포함 비중(%)"].mean(), w2["월세 포함 비중(%)"].mean()
        p1 = w1["월세포함"].sum() / w1["계약수"].sum() * 100
        p2 = w2["월세포함"].sum() / w2["계약수"].sum() * 100
        pl.append({"비교": name, "앞 6개월": f"{a1}~{b1}", "뒤 6개월": f"{a2}~{b2}",
                   "앞 비중(월평균, %)": m1, "뒤 비중(월평균, %)": m2, "차이(%p)": m2 - m1, "차이(합산, %p)": p2 - p1})
    pl = pd.DataFrame(pl)
    placebo_mean = pl.loc[pl["비교"].str.startswith("위약"), "차이(%p)"].mean()
    adj = pl.at[0, "차이(%p)"] - placebo_mean
    pl = pd.concat([pl, pd.DataFrame([
        {"비교": "위약 차이 평균", "차이(%p)": placebo_mean},
        {"비교": "신고제 시점 차이 - 위약 평균", "차이(%p)": adj},
    ])], ignore_index=True)
    pl.to_csv(config.OUT_TAB / "diag_reporting_placebo.csv", index=False, encoding="utf-8-sig")
    print("\n" + pl.round(2).to_string(index=False))

    # 그림: 위 계약 수, 아래 월세 포함 비중 (축 하나씩, x 공유)
    x = pd.to_datetime(t["ym"], format="%Y%m") + pd.Timedelta(days=14)  # 월 중앙
    fig, axes = plt.subplots(2, 1, figsize=(9, 6.2), dpi=150, sharex=True)
    series = [("계약수", "월별 계약 수(건)", "{:,.0f}"), ("월세 포함 비중(%)", "월세 포함 비중(%)", "{:.0f}")]
    for ax, (col, ylab, fmt) in zip(axes, series):
        ax.axvspan(pd.Timestamp(config.GAP_PERIOD[0]), pd.Timestamp(config.GAP_PERIOD[1]), color=BAND, lw=0)
        ax.plot(x, t[col], color=MARK, lw=2)
        for d in [config.LAW_DATE, config.REPORTING_DATE]:
            ax.axvline(pd.Timestamp(d), color=INK2, lw=1, ls="--")
        ax.set_ylabel(ylab, color=INK, fontsize=9)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _, f=fmt: f.format(v)))
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=8)
    top = axes[0]
    ymax = top.get_ylim()[1]
    top.text(pd.Timestamp(config.LAW_DATE), ymax, " 임대차 2법 시행\n 2020.7.31.", fontsize=7.5, color=INK2, va="top")
    top.text(pd.Timestamp(config.REPORTING_DATE), ymax, " 전월세신고제 시행\n 2021.6.1.", fontsize=7.5, color=INK2,
             va="top")
    axes[1].text(pd.Timestamp("2021-08-15"), axes[1].get_ylim()[0], "회색: 사이 기간(진단 전용)", fontsize=7, color=INK2,
             va="bottom", ha="center")
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(bymonth=[2, 8]))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y.%m"))
    fig.suptitle("서울 아파트 전월세 계약: 월별 계약 수와 월세 포함 비중 (2018.8.~2024.7.)",
                 x=0.07, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(config.OUT_FIG / "08c_monthly_trend.png")
    print("그림 저장: outputs/figures/08c_monthly_trend.png")


if __name__ == "__main__":
    main()

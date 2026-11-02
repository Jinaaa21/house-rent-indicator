"""08e. 행정동 주택 재고 특성과 dLQ_exist·RG의 상관 (Pearson, Spearman, 동 부트스트랩 90% 구간).

재고 특성(공공임대·invalid 제외 계약 기준):
  old_share   노후 단지 비중: 시행 전 계약 중 준공 1999년 이하(2019년 기준 20년 이상) 단지 계약 비율
  small_share 60㎡ 이하 비중: 시행 전 계약 중 전용면적 60㎡ 이하 비율
  new_share   신규 공급 비중: 시행 후 계약 중 준공 2018년 이후 단지 계약 비율
  LQ_pre      시행 전 LQ(준공 2017년 이하 단지, dLQ_exist와 같은 범위)
지표는 각 지표의 최소 건수를 충족하고 해석 유보가 아닌 동만.
시행 전 LQ와 ΔLQ의 상관은 같은 LQ_전이 양쪽에 들어가 부풀려지므로, 기준·변화를 다른 해로 나눈 값(08d)과 함께 읽는다.

출력: outputs/tables/stock_corr.csv, data/processed/stock_features.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OLD_MAX, SMALL_MAX, NEW_MIN = 1999, 60, 2018
B, SEED = 1000, 20261102


def features() -> pd.DataFrame:
    r = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    r = r[~r["invalid_rent"] & ~r["public_rental"]]
    pre, post = r[r["period"] == "pre"], r[r["period"] == "post"]
    f = pd.DataFrame({
        "old_share": pre.groupby("adm_cd")["build_year"].apply(lambda s: (s <= OLD_MAX).mean()),
        "small_share": pre.groupby("adm_cd")["area"].apply(lambda s: (s <= SMALL_MAX).mean()),
        "new_share": post.groupby("adm_cd")["build_year"].apply(lambda s: (s >= NEW_MIN).mean()),
    })
    return f


def main() -> None:
    f = features()
    lq = pd.read_csv(config.DATA_PROCESSED / "indicator_lq.csv", dtype={"adm_cd": str}).set_index("adm_cd")
    rg = pd.read_csv(config.DATA_PROCESSED / "indicator_rg.csv", dtype={"adm_cd": str}).set_index("adm_cd")
    f["LQ_pre"] = lq["LQ_pre_exist"]
    f.round(4).to_csv(config.DATA_PROCESSED / "stock_features.csv", encoding="utf-8-sig")
    targets = {"dLQ_exist": lq["dLQ_exist"].where(lq["ok_exist"] & ~lq["hold"]),
               "RG": rg["RG"].where(rg["ok"] & ~rg["hold"])}
    labels = {"old_share": "노후 단지 비중(준공 1999년 이하, 시행 전)", "small_share": "60㎡ 이하 비중(시행 전)",
              "new_share": "신규 공급 비중(준공 2018년 이후, 시행 후)", "LQ_pre": "시행 전 LQ(기존 단지)"}
    rng = np.random.default_rng(SEED)
    rows = []
    for t, y in targets.items():
        for c, lab in labels.items():
            d = pd.concat([f[c], y], axis=1).dropna()
            x, yy = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
            n = len(d)
            pear = np.corrcoef(x, yy)[0, 1]
            spear = pd.Series(x).rank().corr(pd.Series(yy).rank())
            idx = rng.integers(0, n, (B, n))
            bp = np.array([np.corrcoef(x[i], yy[i])[0, 1] for i in idx])
            bs = np.array([pd.Series(x[i]).rank().corr(pd.Series(yy[i]).rank()) for i in idx])
            rows.append({"지표": t, "재고 특성": lab, "동 수": n, "Pearson": pear,
                         "P_lo": np.percentile(bp, 5), "P_hi": np.percentile(bp, 95), "Spearman": spear,
                         "S_lo": np.percentile(bs, 5), "S_hi": np.percentile(bs, 95)})
    # 참고: 소형 비중과 시행 전 LQ(소형 위주 동이 시행 전부터 월세 비중이 높았는지)
    ok = lq["ok_exist"] & ~lq["hold"]
    d = pd.concat([f["small_share"], f["LQ_pre"].where(ok)], axis=1).dropna()
    x, yy = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    idx = rng.integers(0, len(d), (B, len(d)))
    bp = np.array([np.corrcoef(x[i], yy[i])[0, 1] for i in idx])
    bs = np.array([pd.Series(x[i]).rank().corr(pd.Series(yy[i]).rank()) for i in idx])
    rows.append({"지표": "LQ_pre(참고)", "재고 특성": labels["small_share"], "동 수": len(d),
                 "Pearson": np.corrcoef(x, yy)[0, 1], "P_lo": np.percentile(bp, 5), "P_hi": np.percentile(bp, 95),
                 "Spearman": pd.Series(x).rank().corr(pd.Series(yy).rank()),
                 "S_lo": np.percentile(bs, 5), "S_hi": np.percentile(bs, 95)})
    res = pd.DataFrame(rows)
    res.to_csv(config.OUT_TAB / "stock_corr.csv", index=False, encoding="utf-8-sig")
    print(res.round(3).to_string(index=False))
    print("\n재고 특성 분포(동 중위):", f[list(labels)].median().round(3).to_dict())


if __name__ == "__main__":
    main()

"""08b. 진단 보완: 잠원동 제외분 영향 범위, 결합 불일치 단지 확인표, 기존 단지 기준 재계산.

1) 좌표 실패로 제외된 잠원동 단지 계약을 모두 잠원동 / 모두 반포3동에 넣은 두 극단에서
   두 동의 LQ(두 기간)·ΔLQ·R과 ΔLQ 순위를 비교
2) 계약 500건 이상 행정동 불일치 단지 확인표 (수동 확인용)
3) 두 기간 모두 계약이 있는 aptSeq만으로 R·ΔLQ 재계산, 신규 단지 요약

ΔLQ·R 계산은 08_diagnostics.dong_table과 같다.
출력: outputs/tables/diag_jamwon_bounds.csv, join_error_verify_list.csv,
      diag_existing_complex.csv, diag_new_complex.csv
"""
import importlib
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

diag = importlib.import_module("08_diagnostics")
OUT = config.OUT_TAB


def corr(t: pd.DataFrame) -> dict:
    d = t[t["ok"]]
    return {"동 수": len(d), "Pearson": d["R"].corr(d["dLQ"]),
            "Spearman": d["R"].rank().corr(d["dLQ"].rank())}


def main() -> None:
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    clean = pd.read_parquet(config.DATA_INTERIM / "rent_clean.parquet")
    adm = diag_adm()

    # ── 1. 잠원동 두 극단 ───────────────────────────────
    fail = pd.read_csv(OUT / "geocode_fail_assignment.csv")
    jam = fail[fail["bjd"].eq("잠원동") & fail["result"].str.startswith("제외")]
    extra = clean[clean["aptSeq"].isin(jam["aptSeq"])].copy()
    targets = {"잠원동": "서울특별시 서초구 잠원동", "반포3동": "서울특별시 서초구 반포3동"}
    rows = []
    for scen, nm in [("기본(제외)", None)] + [(f"모두 {k}", v) for k, v in targets.items()]:
        r = rent
        if nm:
            a = adm[adm["adm_nm"] == nm].iloc[0]
            e = extra.assign(adm_cd=a["adm_cd"], adm_cd2=a["adm_cd2"], adm_nm=nm, adm_gu="서초구")
            r = pd.concat([rent, e], ignore_index=True)
        t = diag.dong_table(r)
        t = t[t["ok"]].copy()
        t["dLQ_rank"] = t["dLQ"].rank(ascending=False, method="min").astype(int)  # 1 = 가장 큼
        for nm2 in targets.values():
            x = t[t["adm_nm"] == nm2].iloc[0]
            rows.append({"시나리오": scen, "행정동": nm2.split()[-1], "N_pre": x["N_pre"], "N_post": x["N_post"],
                         "LQ_pre": x["LQ_pre"], "LQ_post": x["LQ_post"], "dLQ": x["dLQ"],
                         "dLQ 순위(410개 중)": x["dLQ_rank"], "R": x["R"]})
    jb = pd.DataFrame(rows)
    jb.to_csv(OUT / "diag_jamwon_bounds.csv", index=False, encoding="utf-8-sig")
    print(f"잠원동 제외 단지 {len(jam)}개, 계약 {len(extra)}건 (기간: {extra['period'].value_counts().to_dict()})")
    print(jb.round(3).to_string(index=False))

    # ── 2. 500건 이상 불일치 단지 확인표 ─────────────────
    e5 = pd.read_csv(OUT / "join_error_500plus.csv", dtype={"adm_cd": str, "vworld_adm_cd": str})
    info = (clean.groupby("aptSeq").agg(단지명=("aptNm", "first"), 구=("gu", "first"), 법정동=("umdNm", "first"),
                                         지번=("jibun", "first"), 도로명=("roadnm", "first")))
    v = e5.join(info, on="aptSeq")
    v = v[["aptSeq", "단지명", "구", "법정동", "지번", "도로명", "adm_cd", "adm_nm", "vworld_adm_cd",
           "vworld_adm_nm", "n"]].rename(columns={"adm_cd": "경계결합_adm_cd", "adm_nm": "경계결합_동",
                                                   "vworld_adm_cd": "VWorld_adm_cd", "vworld_adm_nm": "VWorld_동",
                                                   "n": "계약 수"})
    v.to_csv(OUT / "join_error_verify_list.csv", index=False, encoding="utf-8-sig")
    print("\n" + v.to_string(index=False))

    # ── 3. 기존 단지 기준 재계산 ────────────────────────
    per = rent.groupby("aptSeq")["period"].agg(set)
    both = per[per.apply(lambda s: s == {"pre", "post"})].index
    post_only = per[per.apply(lambda s: s == {"post"})].index
    pre_only = per[per.apply(lambda s: s == {"pre"})].index
    # 기존 단지 두 정의: (가) 두 기간 모두 계약 있는 aptSeq, (나) 준공연도 ≤ EXIST_MAX_BUILD_YEAR
    versions = {
        "기본": diag.dong_table(rent),
        "양 기간 계약 단지": diag.dong_table(rent[rent["aptSeq"].isin(both)]),
        f"준공 {config.EXIST_MAX_BUILD_YEAR}년 이하": diag.dong_table(rent[rent["build_year"] <= config.EXIST_MAX_BUILD_YEAR]),
    }
    base = versions["기본"]
    rows3 = []
    for k, t in versions.items():
        c, ok = corr(t), t[t["ok"]]
        m = base.merge(t[["adm_cd", "dLQ", "ok"]], on="adm_cd", suffixes=("", "_v"))
        m = m[m["ok"] & m["ok_v"]]
        rows3.append({"버전": k, "대상 동 수": c["동 수"], "R–ΔLQ Pearson": c["Pearson"],
                      "R–ΔLQ Spearman": c["Spearman"], "R 중위값": ok["R"].median(),
                      "R 95% 분위": ok["R"].quantile(.95), "R 최댓값": ok["R"].max(),
                      "ΔLQ 기본과 상관": m["dLQ"].corr(m["dLQ_v"])})
    cmp_ = pd.DataFrame(rows3)
    exist = versions[f"준공 {config.EXIST_MAX_BUILD_YEAR}년 이하"]
    cmp_.to_csv(OUT / "diag_existing_complex.csv", index=False, encoding="utf-8-sig")
    print("\n" + cmp_.round(3).to_string(index=False))

    small = rent["area"] < config.SMALL_AREA
    grp = pd.Series("양 기간", index=rent.index)
    grp[rent["aptSeq"].isin(post_only)] = "시행 후에만(신규)"
    grp[rent["aptSeq"].isin(pre_only)] = "시행 전에만"
    nc = (rent.assign(grp=grp, small=small, monthly=rent["rent_type"].eq("월세 포함"))
              .groupby(["grp", "period"]).agg(단지=("aptSeq", "nunique"), 계약=("aptSeq", "size"),
                                              소형비중=("small", "mean"), 월세포함비중=("monthly", "mean"))
              .reset_index())
    nc[["소형비중", "월세포함비중"]] = (nc[["소형비중", "월세포함비중"]] * 100).round(2)
    nc.to_csv(OUT / "diag_new_complex.csv", index=False, encoding="utf-8-sig")
    print("\n" + nc.to_string(index=False))
    tot_post = (rent["period"] == "post").sum()
    newn = rent["aptSeq"].isin(post_only).sum()
    print(f"신규 단지 계약 {newn:,}건 = 시행 후 계약의 {newn / tot_post * 100:.1f}%")
    top = (exist[exist["ok"]].nlargest(5, "R")[["adm_gu", "adm_nm", "N_pre", "N_post", "R", "dLQ"]])
    print("기존 단지 기준 R 상위:\n" + top.round(2).to_string(index=False))


def diag_adm() -> pd.DataFrame:
    import geopandas as gpd
    g = gpd.read_file(config.ADMDONG_FILE)
    return pd.DataFrame(g[g["sidonm"] == "서울특별시"][["adm_cd", "adm_cd2", "adm_nm"]])


if __name__ == "__main__":
    main()

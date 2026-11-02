"""04. 행정동 결합: 단지 좌표(aptSeq) × 행정동 경계 point-in-polygon (analysis_plan.md 4.2의 7단계).

입력: data/interim/complex_coords.csv, data/interim/rent_clean.parquet, config.ADMDONG_FILE
출력: data/interim/rent_admdong.parquet        계약 + 행정동
      outputs/tables/admdong_counts.csv          행정동별·기간별 계약 수
      outputs/tables/dup_ratio_admdong.csv       행정동별·기간별 완전 중복 비율
      outputs/tables/join_check.csv              구 불일치·지오코더 행정동 불일치 단지
      outputs/tables/preprocess_log.csv          6·7단계 행 추가
"""
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

PERIOD_LABEL = {"pre": "시행 전", "post": "시행 후"}


def load_admdong() -> gpd.GeoDataFrame:
    if not config.ADMDONG_FILE.exists():
        import urllib.request
        urllib.request.urlretrieve(config.ADMDONG_URL, config.ADMDONG_FILE)
    g = gpd.read_file(config.ADMDONG_FILE)
    # 행정동 키: adm_cd(통계청 8자리). adm_cd2(행안부 10자리), adm_nm도 보관. 결합은 EPSG:5179
    g = g[g["sidonm"] == "서울특별시"][["adm_cd", "adm_cd2", "adm_nm", "sgg", "sggnm", "geometry"]]
    return g.rename(columns={"sgg": "adm_sgg", "sggnm": "adm_gu"}).to_crs(epsg=5179)


def log_rows(df: pd.DataFrame, step: str, rule: str, flagged=None) -> dict:
    row = {"단계": step, "기준": rule, "전체": len(df)}
    for p, lab in PERIOD_LABEL.items():
        row[lab] = int((df["period"] == p).sum())
    if flagged is not None:
        row["표시 건수"] = int(flagged.sum())
        for p, lab in PERIOD_LABEL.items():
            row[f"표시({lab})"] = int((flagged & (df["period"] == p)).sum())
    return row


def lq_by_dong(rent: pd.DataFrame, dong_col: str) -> pd.DataFrame:
    """행정동·기간별 LQ (analysis_plan.md 3.1). invalid_rent 제외."""
    r = rent[~rent["invalid_rent"]]
    g = r.groupby([dong_col, "period"]).agg(N=("rent_type", "size"),
                                             M=("rent_type", lambda s: (s == "월세 포함").sum())).reset_index()
    seoul = r.groupby("period")["rent_type"].apply(lambda s: (s == "월세 포함").mean())
    g["LQ"] = g["M"] / g["N"] / g["period"].map(seoul)
    return g.pivot(index=dong_col, columns="period", values=["N", "LQ"])


def main() -> None:
    adm = load_admdong()
    cx = pd.read_csv(config.DATA_INTERIM / "complex_coords.csv", dtype={"h_code": str})
    has_xy = cx["x"].notna() & cx["y"].notna()
    pts = gpd.GeoDataFrame(cx[has_xy], geometry=gpd.points_from_xy(cx.loc[has_xy, "x"], cx.loc[has_xy, "y"]),
                           crs="EPSG:4326").to_crs(epsg=5179)
    j = gpd.sjoin(pts, adm, how="left", predicate="within").drop(columns=["index_right"])
    j = j.drop_duplicates("aptSeq")  # 경계선 위 점이 두 동에 걸리면 첫 번째
    j["assign_method"] = "pip"

    # 점검: 원자료 구(aptSeq 앞 5자리)와 결합된 행정동의 구, 지오코더가 준 행정동 코드와 결합 결과
    j["sgg_raw"] = j["aptSeq"].str[:5]
    j["gu_mismatch"] = j["adm_sgg"].notna() & (j["adm_sgg"] != j["sgg_raw"])
    # 지오코더가 행정동 코드(10자리)를 주는 경우에만 adm_cd2와 대조. VWorld 코드는 정답으로 쓰지 않음
    j["h_mismatch"] = j["h_code"].notna() & j["adm_cd2"].notna() & (j["h_code"] != j["adm_cd2"])
    j.drop(columns="geometry").loc[j["gu_mismatch"] | j["h_mismatch"]].to_csv(
        config.OUT_TAB / "join_check.csv", index=False, encoding="utf-8-sig")
    print(f"단지 {len(cx):,}개: 좌표 있음 {int(has_xy.sum()):,}, 구 불일치 {int(j['gu_mismatch'].sum())}, "
          f"지오코더 행정동과 불일치 {int(j['h_mismatch'].sum())}")

    rent = pd.read_parquet(config.DATA_INTERIM / "rent_clean.parquet")
    n_by_apt = rent["aptSeq"].value_counts()

    # ── 7a. 구 불일치: 원자료 구 안에서 가장 가까운 행정동으로 재배정 ──
    adm_cols = ["adm_cd", "adm_cd2", "adm_nm", "adm_sgg", "adm_gu"]
    moved = []
    for i in j.index[j["gu_mismatch"]]:
        cand = adm[adm["adm_sgg"] == j.at[i, "sgg_raw"]]
        dist = cand.geometry.distance(j.at[i, "geometry"])
        k = dist.idxmin()
        moved.append({"aptSeq": j.at[i, "aptSeq"], "address": j.at[i, "address"],
                      "n": int(n_by_apt[j.at[i, "aptSeq"]]),
                      "before_adm_cd": j.at[i, "adm_cd"], "before_adm_nm": j.at[i, "adm_nm"],
                      "after_adm_cd": cand.at[k, "adm_cd"], "after_adm_nm": cand.at[k, "adm_nm"],
                      "dist_m": round(float(dist[k]), 1)})
        j.loc[i, adm_cols] = cand.loc[k, adm_cols].values
        j.at[i, "assign_method"] = "nearest_in_gu"
    pd.DataFrame(moved).to_csv(config.OUT_TAB / "join_reassigned_gu.csv", index=False, encoding="utf-8-sig")

    # ── 7b. 좌표 실패 단지: 같은 법정동의 단지가 모두 한 행정동에 있으면 그 동으로 (bjd_unique) ──
    bjd = (rent.groupby(["aptSeq", "sggCd", "umdNm"]).size().reset_index(name="n")
               .sort_values("n", ascending=False).drop_duplicates("aptSeq").set_index("aptSeq"))
    j = pd.DataFrame(j.drop(columns="geometry")).join(bjd[["sggCd", "umdNm"]], on="aptSeq")
    dong_sets = j.groupby(["sggCd", "umdNm"])["adm_cd"].unique()
    adm_by_cd = adm.set_index("adm_cd")
    addr_by_apt = cx.set_index("aptSeq")["address"]
    fail_rows, add_rows = [], []
    for apt in cx.loc[~has_xy, "aptSeq"]:
        key = (bjd.at[apt, "sggCd"], bjd.at[apt, "umdNm"])
        cands = list(dong_sets.get(key, []))
        row = {"aptSeq": apt, "address": addr_by_apt[apt], "n": int(n_by_apt[apt]),
               "bjd": key[1], "n_admdong_in_bjd": len(cands)}
        if len(cands) == 1:
            a = adm_by_cd.loc[cands[0]]
            add_rows.append({"aptSeq": apt, "address": addr_by_apt[apt], "match": "fail",
                             "adm_cd": cands[0], "adm_cd2": a["adm_cd2"], "adm_nm": a["adm_nm"],
                             "adm_sgg": a["adm_sgg"], "adm_gu": a["adm_gu"], "assign_method": "bjd_unique"})
            row.update(result="bjd_unique", adm_nm=a["adm_nm"])
        else:
            row.update(result="제외(법정동이 여러 행정동에 걸침)" if cands else "제외(같은 법정동 단지 없음)",
                       adm_nm="; ".join(adm_by_cd.loc[cands, "adm_nm"]))
        fail_rows.append(row)
    j = pd.concat([j, pd.DataFrame(add_rows)], ignore_index=True)
    pd.DataFrame(fail_rows).to_csv(config.OUT_TAB / "geocode_fail_assignment.csv", index=False, encoding="utf-8-sig")

    # ── 7c. 수동 확인(manual_verified): data/manual/admdong_manual_verified.csv의 verified_adm_nm이 있으면 우선 ──
    manual_path = config.ROOT / "data" / "manual" / "admdong_manual_verified.csv"
    if manual_path.exists():
        man = pd.read_csv(manual_path, dtype=str).fillna("")
        man = man[man["verified_adm_nm"].str.strip() != ""]
        by_nm = adm.set_index("adm_nm")
        for _, mrow in man.iterrows():
            nm = mrow["verified_adm_nm"].strip()
            nm = nm if nm.startswith("서울특별시") else f"서울특별시 {mrow['구']} {nm}"  # '청림동'만 적어도 됨
            if nm not in by_nm.index:
                sys.exit(f"수동 확인 행정동 이름을 경계 파일에서 찾지 못함: {mrow['aptSeq']} → {nm}")
            a = by_nm.loc[nm]
            sel = j["aptSeq"] == mrow["aptSeq"]
            j.loc[sel, ["adm_cd", "adm_cd2", "adm_nm", "adm_sgg", "adm_gu"]] = \
                [a["adm_cd"], a["adm_cd2"], nm, a["adm_sgg"], a["adm_gu"]]
            j.loc[sel, "assign_method"] = "manual_verified"
        print(f"수동 확인 반영: {len(man)}개 단지")

    rent = rent.merge(j[["aptSeq", "match", "assign_method", "adm_cd", "adm_cd2", "adm_nm", "adm_gu"]],
                      on="aptSeq", how="left")
    rent = rent.rename(columns={"match": "geo_match"})
    no_geo = rent["geo_match"].isna() | rent["geo_match"].eq("fail")
    no_adm = rent["adm_cd"].isna()

    # ── 결합 오차 점검: 계약 500건 이상 행정동 불일치 단지를 VWorld 쪽 동으로 옮겼을 때 LQ 변화 ──
    hm = j[j["h_mismatch"].eq(True) & j["gu_mismatch"].eq(False)].copy()
    hm["n"] = hm["aptSeq"].map(n_by_apt)
    hm = hm[hm["n"] >= 500]
    code2 = adm.set_index("adm_cd2")
    hm["vworld_adm_cd"] = hm["h_code"].map(code2["adm_cd"])
    hm["vworld_adm_nm"] = hm["h_code"].map(code2["adm_nm"])
    hm[["aptSeq", "address", "n", "adm_cd", "adm_nm", "vworld_adm_cd", "vworld_adm_nm"]].to_csv(
        config.OUT_TAB / "join_error_500plus.csv", index=False, encoding="utf-8-sig")
    alt = rent[~no_adm].copy()
    alt["adm_alt"] = alt["adm_cd"]
    sel = alt["aptSeq"].isin(hm["aptSeq"])
    alt.loc[sel, "adm_alt"] = alt.loc[sel, "aptSeq"].map(hm.set_index("aptSeq")["vworld_adm_cd"])
    base, mov = lq_by_dong(alt, "adm_cd"), lq_by_dong(alt, "adm_alt")
    touched = sorted(set(hm["adm_cd"]) | set(hm["vworld_adm_cd"]))
    sens = pd.DataFrame(index=pd.Index(touched, name="adm_cd"))
    sens["adm_nm"] = adm_by_cd.loc[touched, "adm_nm"].values
    for p in ["pre", "post"]:
        sens[f"N_{p}"] = base[("N", p)].reindex(touched).values
        sens[f"N_{p}_moved"] = mov[("N", p)].reindex(touched).values
        sens[f"LQ_{p}"] = base[("LQ", p)].reindex(touched).round(3).values
        sens[f"LQ_{p}_moved"] = mov[("LQ", p)].reindex(touched).round(3).values
        sens[f"chg_LQ_{p}"] = (sens[f"LQ_{p}_moved"] - sens[f"LQ_{p}"]).round(3)
    sens["chg_dLQ"] = (sens["chg_LQ_post"] - sens["chg_LQ_pre"]).round(3)
    sens.reset_index().to_csv(config.OUT_TAB / "join_error_lq_sensitivity.csv", index=False, encoding="utf-8-sig")

    logs = [
        log_rows(rent, "6. 지오코딩", "브이월드 지오코더, aptSeq별 거래 최다 주소 좌표, 좌표 없음 표시", no_geo),
        log_rows(rent, "6a. 지번 정확 일치 외", "geo_match ≠ jibun_exact 표시(행 유지)",
                 rent["geo_match"].ne("jibun_exact") & ~no_geo),
        log_rows(rent, "7. 행정동 결합", f"admdongkor {config.ADMDONG_VERSION} point-in-polygon(EPSG:5179)",
                 rent["assign_method"].eq("pip")),
        log_rows(rent, "7a. 구 불일치 재배정", "원자료 구 안의 가장 가까운 행정동(nearest_in_gu)",
                 rent["assign_method"].eq("nearest_in_gu")),
        log_rows(rent, "7b. 좌표 실패 배정", "같은 법정동 단지가 모두 한 행정동이면 그 동(bjd_unique)",
                 rent["assign_method"].eq("bjd_unique")),
        log_rows(rent, "7c. 수동 확인 배정", "data/manual/admdong_manual_verified.csv(manual_verified)",
                 rent["assign_method"].eq("manual_verified")),
        log_rows(rent.loc[~no_adm], "7d. 행정동 미배정 제외",
                 f"법정동이 여러 행정동에 걸친 좌표 실패 단지 {int(no_adm.sum())}건 제외"),
    ]
    rent = rent[~no_adm].copy()

    log_path = config.OUT_TAB / "preprocess_log.csv"
    plog = pd.read_csv(log_path)
    plog = plog[~plog["단계"].str.match(r"^(6|7)")]
    pd.concat([plog, pd.DataFrame(logs)], ignore_index=True).to_csv(log_path, index=False, encoding="utf-8-sig")

    rent.to_parquet(config.DATA_INTERIM / "rent_admdong.parquet", index=False)

    # 행정동별 건수 (경계상의 모든 동 포함: 계약 0건 동도 남김)
    cnt = (rent.groupby(["adm_cd", "period"]).size().unstack(fill_value=0)
               .rename(columns=PERIOD_LABEL))
    cnt = adm[["adm_cd", "adm_cd2", "adm_gu", "adm_nm"]].merge(cnt, on="adm_cd", how="left").fillna({"시행 전": 0, "시행 후": 0})
    cnt[["시행 전", "시행 후"]] = cnt[["시행 전", "시행 후"]].astype(int)
    cnt["LQ 표시 가능"] = (cnt["시행 전"] >= config.MIN_N_LQ) & (cnt["시행 후"] >= config.MIN_N_LQ)
    cnt.to_csv(config.OUT_TAB / "admdong_counts.csv", index=False, encoding="utf-8-sig")

    dup = (rent.groupby(["adm_cd", "adm_nm", "period"])
               .agg(n=("dup_extra", "size"), n_dup_extra=("dup_extra", "sum")).reset_index())
    dup["dup_pct"] = (dup["n_dup_extra"] / dup["n"] * 100).round(2)
    dup.to_csv(config.OUT_TAB / "dup_ratio_admdong.csv", index=False, encoding="utf-8-sig")

    print(f"행정동 {len(cnt)}개 중 계약 있음(두 기간 합) {int((cnt['시행 전'] + cnt['시행 후'] > 0).sum())}, "
          f"두 기간 모두 N ≥ {config.MIN_N_LQ}: {int(cnt['LQ 표시 가능'].sum())}")
    print(cnt[["시행 전", "시행 후"]].describe().round(1).to_string())


if __name__ == "__main__":
    main()

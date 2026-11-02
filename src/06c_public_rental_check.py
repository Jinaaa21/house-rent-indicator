"""06c. g = 0 묶음 점검과 공공임대 표시 단지 목록.

- 공공임대 표시(02의 public_rental, 단지명 키워드)를 포함한 매칭 묶음(rg_cells_incl)에서
  g가 정확히 0인 묶음의 단지 목록과 공공임대 표시 단지의 비중
- 공공임대 표시 단지 목록 (이름만으로는 확정 불가 → [확인 필요])
공공임대 포함/제외 지표 비교는 05(lq_public_sensitivity.csv)·06(rg_public_sensitivity.csv)에 있다.

입력: data/interim/rg_cells_incl.parquet, rent_admdong.parquet
출력: outputs/tables/g0_complexes.csv, public_rental_flag.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OUT = config.OUT_TAB


def main() -> None:
    cells = pd.read_parquet(config.DATA_INTERIM / "rg_cells_incl.parquet")
    rent = pd.read_parquet(config.DATA_INTERIM / "rent_admdong.parquet")
    info = rent.groupby("aptSeq").agg(단지명=("aptNm", "first"), 구=("adm_gu", "first"), 행정동=("adm_nm", "first"),
                                      준공연도=("build_year", "first"), 전체계약=("aptSeq", "size"),
                                      공공임대_표시=("public_rental", "first"))
    info["행정동"] = info["행정동"].str.split().str[-1]
    info["키워드"] = info["단지명"].str.extract(f"({config.PUBLIC_RENTAL_PATTERN})", expand=False)
    info["판단 근거"] = np.where(info["공공임대_표시"], "단지명 키워드만 [확인 필요]", "")
    info[info["공공임대_표시"]].sort_values("전체계약", ascending=False).to_csv(
        OUT / "public_rental_flag.csv", encoding="utf-8-sig")

    cells["n"] = cells["size_y1"] + cells["size_y2"]
    cells["g0"] = cells["g"] == 0
    cells = cells.join(info[["공공임대_표시"]], on="aptSeq")
    g0 = (cells[cells["g0"]].groupby("aptSeq").agg(g0_묶음=("g", "size"), g0_계약=("n", "sum"))
              .join(cells.groupby("aptSeq").agg(전체_묶음=("g", "size")))
              .join(info).sort_values("g0_계약", ascending=False))
    g0.to_csv(OUT / "g0_complexes.csv", encoding="utf-8-sig")
    print(f"g = 0 묶음 {int(cells['g0'].sum()):,}개 / 전체 {len(cells):,}개 ({cells['g0'].mean() * 100:.1f}%), "
          f"단지 {len(g0):,}개")
    print(g0[["단지명", "구", "준공연도", "g0_묶음", "전체_묶음", "g0_계약", "공공임대_표시"]].head(25).to_string())

    pub = cells["공공임대_표시"].astype(bool)
    print(f"\n공공임대 표시 단지: {int(info['공공임대_표시'].sum())}개 "
          f"(계약 {int(info.loc[info['공공임대_표시'], '전체계약'].sum()):,}건)")
    print(f"g = 0 묶음 중 공공임대 표시 비중: 묶음 {pub[cells['g0']].mean() * 100:.1f}%, "
          f"계약 {cells.loc[cells['g0'] & pub, 'n'].sum() / cells.loc[cells['g0'], 'n'].sum() * 100:.1f}%")
    print(f"공공임대 표시 묶음의 g = 0 비율 {cells.loc[pub, 'g0'].mean() * 100:.1f}% / "
          f"그 외 {cells.loc[~pub, 'g0'].mean() * 100:.1f}%")


if __name__ == "__main__":
    main()

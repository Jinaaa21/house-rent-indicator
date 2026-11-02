"""03. 지오코딩: 고유 지번 주소 → 좌표 (브이월드 지오코더 API 2.0, 일일 40,000건).

1) 지번 주소(type=PARCEL)로 검색해, 응답의 필지 고유번호(level4LC, 19자리)에서 읽은
   산 여부·본번·부번과 법정동이 원자료 지번과 모두 같으면 jibun_exact
2) 아니면 도로명 주소(서울특별시 + 구 + roadnm, type=ROAD)로 다시 검색해 찾으면 road
3) 지번 검색 결과가 있지만 지번이 다르면 approx, 둘 다 없으면 fail
결과는 한 건씩 data/interim/geocode_cache.csv에 덧붙이므로 끊겨도 다시 실행하면 이어서 받는다.
일일 한도 초과(OVER_REQUEST_LIMIT)면 멈춘다.

출력: data/interim/geocode_cache.csv      주소별 결과(캐시)
      data/interim/complex_coords.csv     aptSeq별 좌표 (지번이 둘 이상이면 거래가 가장 많은 지번)
      outputs/tables/geocode_not_exact.csv  jibun_exact가 아닌 주소 목록
      outputs/tables/geocode_summary.csv    정확도별 건수

사용 예:
    python src/03_geocode.py            # 전체
    python src/03_geocode.py --limit 20 # 앞 20개만 (시험)
"""
import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

CACHE = config.DATA_INTERIM / "geocode_cache.csv"
CACHE_COLS = ["address", "query", "match", "x", "y", "matched_address", "pnu",
              "b_name", "h_code", "h_name", "status"]
ERROR_LOG = config.LOG_DIR / "geocode_errors.log"
JIBUN_RE = re.compile(r"^(산)?\s*(\d+)(?:-(\d+))?$")


class QuotaError(RuntimeError):
    pass


def parse_jibun(jibun: str) -> str | None:
    """'산69-1' → '200690001' (필지 고유번호 뒤 9자리: 산 여부 1자리 + 본번 4 + 부번 4). 숫자 지번이 아니면 None."""
    m = JIBUN_RE.match(jibun.strip())
    if not m:
        return None
    return ("2" if m.group(1) else "1") + m.group(2).zfill(4) + (m.group(3) or "0").zfill(4)


def search(session: requests.Session, key: str, query: str, kind: str) -> dict:
    params = {"service": "address", "request": "getCoord", "version": "2.0", "crs": "EPSG:4326",
              "type": kind, "address": query, "refine": "true", "simple": "false",
              "format": "json", "key": key}
    r = session.get(config.GEOCODE_URL, params=params, timeout=15)
    r.raise_for_status()
    res = r.json()["response"]
    if res.get("status") == "ERROR":
        code = (res.get("error") or {}).get("code", "")
        if code == "OVER_REQUEST_LIMIT":
            raise QuotaError(code)
        raise RuntimeError(f"{code} {(res.get('error') or {}).get('text', '')}")
    return res


def row_from(res: dict, address: str, query: str, match: str) -> dict:
    st = (res.get("refined") or {}).get("structure") or {}
    pt = (res.get("result") or {}).get("point") or {}
    return {
        "address": address, "query": query, "match": match,
        "x": pt.get("x"), "y": pt.get("y"),
        "matched_address": (res.get("refined") or {}).get("text"),
        "pnu": st.get("level4LC") or None, "b_name": st.get("level4L"),
        "h_code": st.get("level4AC") or None, "h_name": st.get("level4A"),
        "status": res.get("status"),
    }


def geocode(session, key: str, address: str, jibun: str, umd: str, gu: str, roadnm: str) -> dict:
    target = parse_jibun(jibun)
    res = search(session, key, address, "PARCEL")
    if res.get("status") == "OK":
        st = res["refined"]["structure"]
        pnu = st.get("level4LC") or ""
        if target and len(pnu) == 19 and pnu[10:] == target and st.get("level4L") == umd:
            return row_from(res, address, address, "jibun_exact")

    if roadnm.strip():
        road_q = f"서울특별시 {gu} {roadnm.strip()}"
        time.sleep(config.GEOCODE_SLEEP)
        road = search(session, key, road_q, "ROAD")
        if road.get("status") == "OK":
            return row_from(road, address, road_q, "road")

    if res.get("status") == "OK":
        return row_from(res, address, address, "approx")
    return {"address": address, "query": address, "match": "fail", "status": res.get("status")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N개 주소만 처리(시험용)")
    args = ap.parse_args()

    load_dotenv(config.ROOT / ".env")
    key = os.getenv("VWORLD_KEY", "").strip()
    if not key:
        sys.exit("VWORLD_KEY가 없습니다. .env에 브이월드 API 인증키를 넣으세요.")

    df = pd.read_parquet(config.DATA_INTERIM / "rent_clean.parquet",
                         columns=["aptSeq", "address", "gu", "umdNm", "jibun", "roadnm"])
    # 주소별 대표 도로명(가장 많이 나온 값)과 거래 수
    addr = (df.groupby(["address", "gu", "umdNm", "jibun", "roadnm"]).size().reset_index(name="n")
              .sort_values("n", ascending=False).drop_duplicates("address"))
    done = set(pd.read_csv(CACHE, usecols=["address"])["address"]) if CACHE.exists() else set()
    todo = addr[~addr["address"].isin(done)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"고유 주소 {len(addr):,}개, 캐시 {len(done):,}개, 이번 처리 {len(todo):,}개")

    session = requests.Session()
    new_file = not CACHE.exists()
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CACHE_COLS)
        if new_file:
            w.writeheader()
        for i, r in enumerate(todo.itertuples(index=False), 1):
            try:
                w.writerow(geocode(session, key, r.address, r.jibun, r.umdNm, r.gu, r.roadnm))
                f.flush()
            except QuotaError as e:
                print(f"호출 한도 도달로 중단: {e}. 다시 실행하면 이어서 받습니다.")
                break
            except Exception as e:  # 실패는 캐시에 쓰지 않고 기록 → 재실행 시 다시 시도
                with open(ERROR_LOG, "a", encoding="utf-8") as lf:
                    lf.write(f"{r.address}\t{type(e).__name__}: {e}\n")
            if i % 500 == 0:
                print(f"  {i:,}/{len(todo):,}")
            time.sleep(config.GEOCODE_SLEEP)

    summarize(df, addr)


def summarize(df: pd.DataFrame, addr: pd.DataFrame) -> None:
    cache = pd.read_csv(CACHE, dtype={"pnu": str, "h_code": str}).drop_duplicates("address", keep="last")
    res = addr.merge(cache, on="address", how="left")
    res["match"] = res["match"].fillna("미처리")

    summ = res.groupby("match").agg(주소=("address", "size"), 거래=("n", "sum")).reset_index()
    summ["주소 비율(%)"] = (summ["주소"] / len(res) * 100).round(2)
    summ["거래 비율(%)"] = (summ["거래"] / res["n"].sum() * 100).round(2)
    config.OUT_TAB.mkdir(parents=True, exist_ok=True)
    summ.to_csv(config.OUT_TAB / "geocode_summary.csv", index=False, encoding="utf-8-sig")
    print(summ.to_string(index=False))

    res[res["match"] != "jibun_exact"].sort_values(["match", "n"], ascending=[True, False]).to_csv(
        config.OUT_TAB / "geocode_not_exact.csv", index=False, encoding="utf-8-sig")

    # aptSeq별 좌표: 거래가 가장 많은 지번 주소의 좌표
    by = (df.groupby(["aptSeq", "address"]).size().reset_index(name="n_addr")
            .sort_values("n_addr", ascending=False))
    n_multi = int((by.groupby("aptSeq")["address"].nunique() > 1).sum())
    cx = by.drop_duplicates("aptSeq").merge(cache, on="address", how="left")
    cx = cx[["aptSeq", "address", "n_addr", "match", "x", "y", "h_code", "h_name"]]
    cx.to_csv(config.DATA_INTERIM / "complex_coords.csv", index=False, encoding="utf-8-sig")
    print(f"aptSeq {len(cx):,}개 좌표 저장 (주소 2개 이상 aptSeq {n_multi}개, 거래 최다 주소 사용), 좌표 없음 {int(cx['x'].isna().sum())}개")


if __name__ == "__main__":
    main()

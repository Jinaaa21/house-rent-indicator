"""01. 아파트 전월세 실거래 자료 수집 (공공데이터포털 API).

구(시군구 코드) × 계약연월 단위로 호출해 data/raw/apt_rent_{시군구코드}_{YYYYMM}.csv로 저장한다.
이미 받은 파일은 건너뛰고, 실패한 호출은 logs/collect_errors.log에 남긴 뒤 다음으로 넘어간다.

사용 예:
    python src/01_collect.py --lawd 11680 --ym 202208
    python src/01_collect.py --lawd 11680 11650 --ym 201908 202208
    python src/01_collect.py                # 서울 25개 구 × 두 비교 기간 48개월 전체
"""
import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

# 기술문서(응답 메시지 명세)의 항목 순서. 응답에 없는 항목은 빈 값으로 둔다.
FIELDS = [
    "sggCd", "umdNm", "aptNm", "jibun", "excluUseAr",
    "dealYear", "dealMonth", "dealDay", "deposit", "monthlyRent",
    "floor", "buildYear", "contractTerm", "contractType", "useRRRight",
    "preDeposit", "preMonthlyRent",
    "roadnm", "roadnmsggcd", "roadnmcd", "roadnmseq", "roadnmbcd",
    "roadnmbonbun", "roadnmbubun", "aptSeq",
]
OK_CODES = {"000", "00"}
ERROR_LOG = config.LOG_DIR / "collect_errors.log"


def month_range(start: str, end: str) -> list[str]:
    """'2018-08-01', '2020-07-31' → ['201808', ..., '202007']"""
    return [p.strftime("%Y%m") for p in pd.period_range(start[:7], end[:7], freq="M")]


def default_months() -> list[str]:
    months = []
    for start, end in config.PERIODS.values():
        months += month_range(start, end)
    return months


def log_error(lawd: str, ym: str, msg: str) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{lawd}\t{ym}\t{msg}\n")


def fetch_page(key: str, lawd: str, ym: str, page: int) -> tuple[list[dict], int]:
    params = {
        "serviceKey": key,
        "LAWD_CD": lawd,
        "DEAL_YMD": ym,
        "pageNo": page,
        "numOfRows": config.API_NUM_ROWS,
    }
    r = requests.get(config.API_URL, params=params, timeout=30)
    r.raise_for_status()
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise RuntimeError(f"XML 아님: {r.text[:200]!r}")

    code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
    if code not in OK_CODES:
        msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or r.text[:200]
        raise RuntimeError(f"resultCode={code} {msg.strip()}")

    total = int(root.findtext(".//totalCount") or 0)
    rows = [{c.tag: (c.text or "").strip() for c in item} for item in root.iter("item")]
    return rows, total


def collect_one(key: str, lawd: str, ym: str) -> int | None:
    """한 구·한 달을 모든 페이지에 걸쳐 받는다. 성공 시 건수, 실패 시 None."""
    rows, page = [], 1
    try:
        while True:
            batch, total = fetch_page(key, lawd, ym, page)
            rows += batch
            if not batch or len(rows) >= total:
                break
            page += 1
            time.sleep(config.API_SLEEP)
    except Exception as e:  # 실패는 기록만 하고 넘어간다
        log_error(lawd, ym, f"page={page} {type(e).__name__}: {e}")
        return None

    if len(rows) != total:
        log_error(lawd, ym, f"건수 불일치: 받은 {len(rows)} / totalCount {total}")
        return None

    df = pd.DataFrame(rows)
    extra = [c for c in df.columns if c not in FIELDS]  # 기술문서에 없는 항목도 보존
    df = df.reindex(columns=FIELDS + extra)
    out = config.DATA_RAW / f"apt_rent_{lawd}_{ym}.csv"
    tmp = out.with_suffix(".csv.part")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(out)  # 쓰는 도중 중단돼도 반쪽 파일이 '받은 파일'로 남지 않게
    return len(df)


def main() -> None:
    ap = argparse.ArgumentParser(description="아파트 전월세 실거래 자료 수집")
    ap.add_argument("--lawd", nargs="+", default=list(config.SEOUL_GU),
                    help="시군구 코드 5자리 (기본: 서울 25개 구)")
    ap.add_argument("--ym", nargs="+", default=None,
                    help="계약연월 YYYYMM (기본: 두 비교 기간 48개월)")
    ap.add_argument("--force", action="store_true", help="이미 받은 파일도 다시 받기")
    args = ap.parse_args()

    load_dotenv(config.ROOT / ".env")
    key = os.getenv("DATA_GO_KR_KEY", "").strip()
    if not key:
        sys.exit(
            "DATA_GO_KR_KEY가 없습니다.\n"
            "  1) .env.example을 .env로 복사하고\n"
            "  2) 공공데이터포털 마이페이지의 '일반 인증키(Decoding)' 값을 DATA_GO_KR_KEY=에 넣으세요."
        )
    if "%" in key:  # Encoding 키를 넣은 경우 requests가 한 번 더 인코딩하지 않도록 되돌림
        key = unquote(key)

    months = args.ym or default_months()
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    jobs = [(l, m) for l in args.lawd for m in months]
    n_skip = n_ok = n_fail = 0

    for i, (lawd, ym) in enumerate(jobs, 1):
        out = config.DATA_RAW / f"apt_rent_{lawd}_{ym}.csv"
        if out.exists() and not args.force:
            n_skip += 1
            continue
        n = collect_one(key, lawd, ym)
        if n is None:
            n_fail += 1
            print(f"[{i}/{len(jobs)}] {lawd} {ym} 실패 (로그: {ERROR_LOG.name})")
        else:
            n_ok += 1
            print(f"[{i}/{len(jobs)}] {lawd} {ym} {n:,}건")
        time.sleep(config.API_SLEEP)

    print(f"완료: 신규 {n_ok}, 건너뜀 {n_skip}, 실패 {n_fail}")


if __name__ == "__main__":
    main()

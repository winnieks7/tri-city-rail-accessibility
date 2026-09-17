#!/usr/bin/env python3
"""Archive official, outcome-blind sources for D-city rail dates and scope.

The source list is deliberately independent of OSM availability. Existing raw
snapshots are immutable: the script verifies and records them but never
overwrites a non-empty target.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTDIR = ROOT / "Data/raw/transport/official_sources/d_date_scope"
METADATA = ROOT / "Data/metadata/transport/d_date_scope_source_archive.json"

SOURCES = [
    {
        "id": "GZ_M1_OFFICIAL_HISTORY",
        "authority": "Guangzhou municipal education authority",
        "url": "https://jyj.gz.gov.cn/attachment/6/6824/6824303/7360517.pdf",
        "file": "gz_m1_official_history.pdf",
        "role": "Line 1 first and full-route opening dates",
    },
    {
        "id": "GZ_2009_LINE5_CONTEMPORANEOUS",
        "authority": "China Daily state media carrying the contemporaneous opening report",
        "url": "https://www.chinadaily.com.cn/dfpd/2009-12/29/content_9240420_2.htm",
        "file": "gz_m5_opening_20091228_chinadaily.html",
        "role": "Contemporaneous exact Line 5 opening date",
    },
    {
        "id": "GZ_2010_METRO_OPENINGS_CONTEMPORANEOUS",
        "authority": "China News Service state media carrying the contemporaneous opening report",
        "url": "https://www.chinanews.com.cn/gn/2010/10-30/2623405.shtml",
        "file": "gz_2010_m2_m3_apm_openings_chinanews.html",
        "role": "Contemporaneous Line 2, Line 3 north, Line 8, Guangfo and APM opening sequence",
    },
    {
        "id": "GZ_2016_THREE_LINES_CONTEMPORANEOUS",
        "authority": "People's Daily state media carrying the contemporaneous opening report",
        "url": "http://ccnews.people.com.cn/n1/2016/1229/c141677-28985187.html",
        "file": "gz_m6_m7_guangfo_opening_20161228_peopledaily.html",
        "role": "Contemporaneous Line 6 phase 2, Line 7 phase 1 and Guangfo phase 2 opening date",
    },
    {
        "id": "GZ_TRAM_HZ1_HAIZHU_GOVERNMENT_REPORT",
        "authority": "Guangzhou Haizhu District Government",
        "url": "https://www.gz.gov.cn/zwgk/zjgb/gqgzbg/hzq/content/post_3089576.html",
        "file": "gz_tram_hz1_opening_20141231_haizhu_gov.html",
        "role": "Haizhu Tram trial-operation date and time",
    },
    {
        "id": "GZ_APM_TIANHE_OFFICIAL_YEARBOOK",
        "authority": "Guangzhou Tianhe District Government",
        "url": "https://www.thnet.gov.cn/thxxw/thnjj/201706/505b28b43ddc4cc696e16f6c1efda92d/files/b3cb678a2a604b438677b6b0f3000e6f.pdf",
        "file": "gz_apm_opening_tianhe_official_yearbook.pdf",
        "role": "Official district yearbook confirmation of the 2010-11-08 APM opening",
        "prefer_curl": True,
    },
    {
        "id": "GZ_BASELINE_STATION_LICENSE_2017",
        "authority": "Guangzhou Municipal Government health authority",
        "url": "https://www.gz.gov.cn/gzmedjg/wszfjd/201712/3c082e75952c4e8a80ca51fb89b46042/files/bd3ee20f6a3c47e7b34884be33c2ba4e.pdf",
        "file": "gz_baseline_operating_station_license_2017.pdf",
        "role": "Official pre-baseline operating-station roster for metro and APM components",
    },
    {
        "id": "GZ_2017_FOUR_OPENINGS",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zwgk/zjgb/zfgzbg/content/post_2840353.html",
        "file": "gz_2017_four_openings.html",
        "role": "2017-12-28 baseline activation of Line 4 south, Line 9, Line 13 phase 1 and Knowledge City line",
    },
    {
        "id": "GZ_2018_COMPLETION_REPORT",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zfjgzy/gzsrmzfyjs/sfyjs/zfxxgkml/bmwj/qtwj/content/post_5510657.html",
        "file": "gz_2018_completion_report.html",
        "role": "2018 Line 3 airport, Line 14, Line 21 east and Guangfo Lijiao activations",
    },
    {
        "id": "GZ_M3_AIRPORT_NORTH_CONTEMPORANEOUS",
        "authority": "Guangzhou SASAC",
        "url": "https://gzw.gz.gov.cn/zt/gzgz/content/post_2781834.html",
        "file": "gz_m3_airport_north_20180426.html",
        "role": "Contemporaneous exact 2018-04-26 Airport North opening evidence",
    },
    {
        "id": "GZ_M9_QINGTANG_OPENING",
        "authority": "Yangcheng Evening News carrying the operator timetable and opening notice",
        "url": "https://news.ycwb.com/2018-06/29/content_30037804.htm",
        "file": "gz_m9_qingtang_opening_20180630_ycwb.html",
        "role": "Exact first-train passenger opening of the Line 9 Qingtang infill station",
    },
    {
        "id": "GZ_M21_WEST_OPERATOR",
        "authority": "Guangzhou SASAC / Guangzhou Metro",
        "url": "https://gzw.gz.gov.cn/qy/qydt/content/post_5464442.html",
        "file": "gz_m21_west_20191220.html",
        "role": "Line 21 west section operation start",
    },
    {
        "id": "GZ_M8_NORTH_OPERATOR",
        "authority": "Guangzhou SASAC / Guangzhou Metro",
        "url": "https://gzw.gz.gov.cn/qy/qydt/content/post_6936246.html",
        "file": "gz_m8_north_20201126.html",
        "role": "Line 8 north section opening and two initially closed stations",
    },
    {
        "id": "GZ_M8_RAINBOW_BRIDGE_OPENING",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zt/jrshts/2022n/gqj/tpxw/content/post_8587040.html",
        "file": "gz_m8_rainbow_bridge_20220928.html",
        "role": "Line 8 Rainbow Bridge station opening from first train",
    },
    {
        "id": "GZ_M8_XICUN_OPENING",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/jtfw/content/post_8729201.html",
        "file": "gz_m8_xicun_20221228.html",
        "role": "Line 8 Xicun station and Line 5 transfer activation",
    },
    {
        "id": "GZ_M8_OFFICIAL_EIA_HISTORY",
        "authority": "Guangzhou Municipal Ecology and Environment Bureau",
        "url": "https://sthjj.gz.gov.cn/attachment/7/7510/7510809/9335300.pdf",
        "file": "gz_m8_official_eia_history.pdf",
        "role": "Official retrospective Line 8 section-date history",
    },
    {
        "id": "GZ_M18_OPENING",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zt/jrshts/2021n/gqj/zxxx/jt/content/post_7811714.html",
        "file": "gz_m18_opening_20210928.html",
        "role": "Line 18 first section opening at 14:00",
    },
    {
        "id": "GZ_M22_OPENING",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/content/post_8163126.html",
        "file": "gz_m22_opening_20220331.html",
        "role": "Line 22 first section opening",
    },
    {
        "id": "GZ_M13_2020_SUSPENSION",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/content/post_5848617.html",
        "file": "gz_m13_suspension_20200522.html",
        "role": "Line 13 full suspension start after the 2020-05-22 rainstorm",
    },
    {
        "id": "GZ_M13_2020_FULL_RESTORATION",
        "authority": "Guangzhou Zengcheng District Government",
        "url": "https://www.zc.gov.cn/zfxxgkml/gzszcqjtysj/qt/content/post_5926945.html",
        "file": "gz_m13_full_restoration_20200613.html",
        "role": "Official confirmation that the final Line 13 section resumed on 2020-06-13",
    },
    {
        "id": "GZ_M6_SHAHE_OPENING",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/jtfw/content/post_10050312.html",
        "file": "gz_m6_shahe_opening_20241228.html",
        "role": "Passenger opening of the Line 6 Shahe infill station with Line 11",
    },
    {
        "id": "FS_M3_2024_CONTEMPORANEOUS",
        "authority": "China News Service state media carrying the contemporaneous opening report",
        "url": "https://www.chinanews.com.cn/cj/2024/08-23/10273369.shtml",
        "file": "fs_m3_two_sections_opening_20240823_chinanews.html",
        "role": "Contemporaneous 06:30 opening and disconnected-section evidence for Foshan Line 3",
    },
    {
        "id": "FS_TRAM_GM1_OPERATOR_NOTICE_REPRINT",
        "authority": "Southern Metropolis Daily verbatim republication of the operator notice",
        "url": "https://m.mp.oeeee.com/a/BAAFRD000020240805983136.html",
        "file": "fs_tram_gm1_suspension_20240806_operator_notice_reprint.html",
        "role": "Verbatim operator notice for the Gaoming tram suspension from 2024-08-06",
    },
    {
        "id": "GZ_LOCAL_INTERCITY_2020",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/content/post_6938832.html",
        "file": "gz_local_intercity_20201130.html",
        "role": "Guangqing and Guangzhou East Ring local operation and multi-payment start",
    },
    {
        "id": "GZ_LOCAL_INTERCITY_2024",
        "authority": "Guangzhou Municipal Government",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/jtfw/content/post_9669108.html",
        "file": "gz_local_intercity_four_line_20240526.html",
        "role": "Four-line local operation, through-running and multi-payment start",
    },
    {
        "id": "SZ_SUISHEN_2019_SERVICE_MODEL",
        "authority": "Shenzhen Municipal Government Port Office",
        "url": "https://ka.sz.gov.cn/ztzl/kntgcx/tszs/content/post_6757275.html",
        "file": "sz_suishen_20191215_service_model.html",
        "role": "Suishen opening, railway electronic-ticket and 12306 evidence",
    },
    {
        "id": "NRA_SUISHEN_LOCAL_OPERATOR_TRANSFER_2025",
        "authority": "National Railway Administration Guangzhou Regional Administration",
        "url": "https://www.nra.gov.cn/zzjg/jgj/gzgl/zwgz/202504/t20250401_348368.shtml",
        "file": "nra_suishen_local_operator_transfer_20250311.html",
        "role": "Post-window official evidence that transfer to Shenzhen Metro was still being prepared in 2025",
    },
    {
        "id": "GZ_GUANGSHEN_GUANGZHU_NATIONAL_TICKETING",
        "authority": "Guangzhou Municipal Transportation Bureau",
        "url": "https://jtj.gz.gov.cn/xwdt/gzdt/content/post_7729568.html",
        "file": "gz_guangshen_guangzhu_national_ticketing.html",
        "role": "Train-specific 12306 products for Guangshen and Guangzhu intercity",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def curl_fetch(url: str, partial: Path) -> None:
    completed = subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry",
            "4",
            "--retry-all-errors",
            "--connect-timeout",
            "30",
            "--speed-time",
            "45",
            "--speed-limit",
            "1024",
            "--continue-at",
            "-",
            "--user-agent",
            "Mozilla/5.0 CarbonAnalysis/transport-study",
            "--output",
            str(partial),
            url,
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"curl failed for {url}")


def fetch(url: str, target: Path, prefer_curl: bool = False) -> None:
    if target.exists():
        if target.stat().st_size < 1024:
            raise RuntimeError(f"Immutable target is unexpectedly small: {target}")
        return
    partial = target.with_suffix(target.suffix + ".part")
    if prefer_curl:
        curl_fetch(url, partial)
        if partial.stat().st_size < 1024:
            raise RuntimeError(f"Downloaded source is unexpectedly small: {target.name}")
        if target.suffix == ".pdf" and partial.read_bytes()[:4] != b"%PDF":
            raise RuntimeError(f"Downloaded file lacks a PDF header: {target.name}")
        os.replace(partial, target)
        return
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 CarbonAnalysis/transport-study",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}: {url}")
            with partial.open("wb") as stream:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    stream.write(block)
    except (urllib.error.URLError, OSError, http.client.IncompleteRead) as exc:
        # Some Guangdong-government endpoints negotiate TLS unreliably with
        # Python's bundled OpenSSL but work with the system curl. The fallback
        # still writes only to .part and never overwrites an immutable target.
        try:
            curl_fetch(url, partial)
        except RuntimeError as curl_exc:
            raise RuntimeError(f"Both urllib and curl failed for {url}") from curl_exc
    if partial.stat().st_size < 1024:
        raise RuntimeError(f"Downloaded source is unexpectedly small: {target.name}")
    if target.suffix == ".pdf" and partial.read_bytes()[:4] != b"%PDF":
        raise RuntimeError(f"Downloaded file lacks a PDF header: {target.name}")
    os.replace(partial, target)


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    archived = []
    for item in SOURCES:
        target = OUTDIR / item["file"]
        fetch(item["url"], target, prefer_curl=item.get("prefer_curl", False))
        archived.append(
            {
                **item,
                "local_file": str(target.relative_to(ROOT)),
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
            }
        )
    record = {
        "archive": "development-city official rail date and scope sources",
        "outcome_data_read": False,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": archived,
    }
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    METADATA.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

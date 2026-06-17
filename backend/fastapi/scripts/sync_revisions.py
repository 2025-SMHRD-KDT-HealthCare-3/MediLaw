"""기획서 ⑤ 배치 스케줄러 — 법령 개정 현황 동기화(1일 1회 권장).

법제처 국가법령정보 공동활용 데이터로 4대 법령(+옵션 시행령/규칙)의 전체 버전
타임라인(시행예정/현행/연혁)을 law_revisions 테이블에 upsert(idempotent).
새 개정/시행예정이 생기면 다음 실행에서 자동 반영된다.

사용법:
  python scripts/sync_revisions.py                # 4대 법령
  python scripts/sync_revisions.py --subordinate  # + 시행령·시행규칙
  LAW_OC=<발급키> DB_PATH=data/medilaw.db python scripts/sync_revisions.py

cron 예(매일 04:30):
  30 4 * * * cd /path/backend/fastapi && DB_PATH=data/medilaw.db python scripts/sync_revisions.py >> /var/log/medilaw_sync.log 2>&1
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import lawapi  # noqa: E402
from app.config import DB_PATH, TRACKED_LAWS  # noqa: E402

SUBORDINATE = [" 시행령", " 시행규칙"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subordinate", action="store_true", help="시행령·시행규칙도 함께 동기화")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    names = list(TRACKED_LAWS)
    if args.subordinate:
        names = [b + v for b in TRACKED_LAWS for v in [""] + SUBORDINATE]

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    lawapi.ensure_tables(conn)

    total_versions = 0
    for name in names:
        try:
            versions = lawapi.sync_law(conn, name)
        except lawapi.LawApiError as e:
            print(f"  ✗ {name}: {e}")
            continue
        cur = next((v for v in versions if v["status"] == "현행"), None)
        upc = sum(1 for v in versions if v["status"] == "시행예정")
        hist = sum(1 for v in versions if v["status"] == "연혁")
        eff = cur["effective_on"] if cur else "?"
        print(f"  ✓ {name}: {len(versions)}버전 (현행 시행 {eff} · 시행예정 {upc} · 연혁 {hist})")
        total_versions += len(versions)

    print(f"완료: {len(names)}개 법령, 누적 버전 {total_versions} → {args.db}")


if __name__ == "__main__":
    main()

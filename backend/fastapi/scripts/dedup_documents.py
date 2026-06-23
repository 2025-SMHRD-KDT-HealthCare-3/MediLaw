"""documents 테이블 내용 중복 제거.

ingest_api(expc/ppc)·ingest_guidelines 가 게시판/첨부별로 같은 문서를 여러 번
적재할 수 있어 정리용. 본문(공백 정규화 후) 해시가 같으면 1건만 남기고 삭제.
가장 긴 본문을 가진 행을 보존(추출 품질이 더 나은 쪽). idempotent.

사용: python scripts/dedup_documents.py [--db data/medilaw.db]
"""
import argparse
import hashlib
import re
import sqlite3


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/medilaw.db")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'").fetchone():
        print("documents 테이블 없음 — 정리할 것 없음")
        return

    before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    # (doc_type, body 해시) 그룹별로 본문이 가장 긴 행만 보존
    keep: dict[tuple, tuple] = {}  # key -> (id, len)
    dups: list[int] = []
    for did, dtype, body in conn.execute("SELECT id, doc_type, body FROM documents"):
        key = (dtype, hashlib.md5(_norm(body).encode("utf-8")).hexdigest())
        blen = len(body or "")
        if key in keep:
            kid, klen = keep[key]
            loser = did if blen <= klen else kid
            if blen > klen:
                keep[key] = (did, blen)
            dups.append(loser)
        else:
            keep[key] = (did, blen)

    if dups:
        conn.executemany("DELETE FROM documents WHERE id=?", [(d,) for d in dups])
        conn.commit()
        conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        conn.commit()

    after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    print(f"중복 제거: {len(dups)}건  ({before} → {after})")
    for r in conn.execute("SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type ORDER BY 2 DESC"):
        print(f"  {r[0]:14s} {r[1]}")
    conn.close()


if __name__ == "__main__":
    main()

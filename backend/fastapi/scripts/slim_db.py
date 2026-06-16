"""배포용 슬림: chunks.embedding BLOB 제거 (sqlite-vec의 chunk_vec만 사용).

임베딩이 chunks.embedding(BLOB, numpy 폴백용)과 chunk_vec(sqlite-vec, 실제 검색용)에
중복 저장됨. sqlite-vec만 쓰면 BLOB은 불필요 → 제거 + VACUUM 으로 파일 ~절반.
검색 품질·속도 동일(검색은 chunk_vec 사용). numpy 폴백만 비활성.

사용: python scripts/slim_db.py [--db data/medilaw.db]
주의: 되돌리려면 build_embeddings.py(MODE=rebuild) 재실행 필요.
"""
import argparse
import os
import sqlite3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/medilaw.db")
    args = ap.parse_args()

    before = os.path.getsize(args.db) / 1e6
    conn = sqlite3.connect(args.db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
    if "embedding" not in cols:
        print("이미 슬림 상태(embedding 컬럼 없음).")
    else:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_vec'").fetchone():
            raise SystemExit("chunk_vec(sqlite-vec) 테이블이 없어 슬림 불가 — 임베딩 검색이 깨집니다.")
        print("chunks.embedding 컬럼 제거 중...")
        conn.execute("ALTER TABLE chunks DROP COLUMN embedding")
        conn.commit()
    print("VACUUM 중...")
    conn.execute("VACUUM")
    conn.commit()
    conn.close()
    after = os.path.getsize(args.db) / 1e6
    print(f"완료: {before:.0f}MB → {after:.0f}MB")


if __name__ == "__main__":
    main()

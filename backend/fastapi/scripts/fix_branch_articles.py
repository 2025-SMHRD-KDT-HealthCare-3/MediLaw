"""가지조문(제N조의M) article_no 병합 보정 — idempotent.

법제처 수집 과정에서 '제N조의M' 가지조문(예: 제7조의2, 제28조의2)이 기본 조번호
(article_no='7', '28')로 병합 저장돼, 제7조·제7조의2…제7조의14가 전부 article_no='7'로
겹쳐 있었다. 이 때문에 verify_statute 가 '7의2' 를 못 찾아 실재 조문을 false ERROR(환각)로
오판했다. 본문(content)이 '제N조의M(...)' 로 시작하는 행의 article_no 를 'N의M' 로 바로잡는다.

- 대상: content 가 '^제(\\d+)조의(\\d+)' 로 시작하는 행만(행정규칙 '# ...' 등은 자동 제외).
- article_no 컬럼만 수정 → 임베딩(chunks/chunk_vec, article id 기준)은 무관, 재빌드 불필요.
- idempotent: 이미 'N의M' 인 행은 건너뜀. 반복 실행해도 안전.

사용: python scripts/fix_branch_articles.py            (data/medilaw.db)
      DB_PATH=... python scripts/fix_branch_articles.py --dry-run
"""
import argparse
import os
import re
import sqlite3

_BRANCH_RE = re.compile(r"^제\s*(\d+)\s*조의\s*(\d+)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_PATH", "data/medilaw.db"))
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 대상만 출력")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, article_no, content FROM articles").fetchall()

    fixes: list[tuple[int, str, str]] = []
    for r in rows:
        m = _BRANCH_RE.match((r["content"] or "").lstrip())
        if not m:
            continue
        correct = f"{m.group(1)}의{m.group(2)}"
        if (r["article_no"] or "") != correct:
            fixes.append((r["id"], r["article_no"] or "", correct))

    print(f"대상 DB: {args.db}")
    print(f"보정 대상(가지조문 병합) 행 수: {len(fixes)}")
    for _id, old, new in fixes[:10]:
        print(f"  id={_id}  '{old}' -> '{new}'")
    if len(fixes) > 10:
        print(f"  … 외 {len(fixes) - 10}건")

    if args.dry_run:
        print("[dry-run] 변경하지 않음.")
        return
    if not fixes:
        print("보정할 행이 없습니다(이미 정상).")
        return

    conn.executemany("UPDATE articles SET article_no = ? WHERE id = ?",
                     [(new, _id) for _id, _old, new in fixes])
    conn.commit()
    print(f"완료: {len(fixes)}행 article_no 보정.")


if __name__ == "__main__":
    main()

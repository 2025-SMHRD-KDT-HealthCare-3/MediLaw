#!/usr/bin/env python3
"""RAG 검색 품질 회귀 측정 하니스 (golden set 기반).

scripts/golden_set.json 의 질문을 hybrid_search 로 검색하고,
기대 근거(expected)가 top-k 안에 나오는지 측정한다.

- 지표: hit@3, hit@k(기본 8), MRR(첫 정답 랭크의 역수 평균, 미검출=0)
- 임베딩(text-embedding-3-small)만 사용 — 생성 LLM 미호출(비용 무시 가능)
- 측정 도구이므로 기본 exit code 0. CI 게이트로 쓰려면 --min-hit8 지정.

실행:
    DB_PATH=data/medilaw.db python3 scripts/eval_retrieval.py
    python3 scripts/eval_retrieval.py --top-k 8 --min-hit8 0.7
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# hybrid_search 의 statute 라벨: "의료법 제27조(무면허 의료행위 등 금지)" / "개인정보 보호법 제28조의2(...)"
# → 법령명 + 조번호("27" / "28의2")로 역파싱해 골든셋과 정확 일치 비교.
_LABEL_RE = re.compile(r"^(?P<law>.+?)\s+제(?P<base>\d+)조(?:의(?P<branch>\d+))?")


def _norm(s: str) -> str:
    """공백 제거 + NFKC 정규화 — 제목의 이중 공백·특수문자(ㆍ 등) 표기 편차에 강건한 contains 비교용."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def match_hit(hit, exp: dict) -> bool:
    """Hit 한 건이 기대 근거(exp) 한 건과 일치하는지."""
    etype = exp.get("type", "statute")
    if etype == "statute":
        if hit.source_type != "statute":
            return False
        m = _LABEL_RE.match(hit.label or "")
        if not m:
            return False
        art = m.group("base") + (f"의{m.group('branch')}" if m.group("branch") else "")
        return m.group("law") == exp["law"] and art == exp["article"]
    if etype == "doc":
        # interpretation / decision / guideline — Hit.source_type 이 doc_type 그대로
        if hit.source_type != exp.get("doc_type"):
            return False
        needle = _norm(exp.get("title_contains", ""))
        return bool(needle) and needle in _norm(hit.title or hit.label)
    if etype == "case":
        if hit.source_type != "case":
            return False
        needle = _norm(exp.get("label_contains", ""))
        return bool(needle) and (needle in _norm(hit.label) or needle in _norm(hit.title))
    return False


def first_match_rank(hits, expected: list[dict]) -> tuple[int | None, str]:
    """첫 정답 랭크(1-base)와 매칭된 라벨. 미검출이면 (None, '')."""
    for rank, hit in enumerate(hits, start=1):
        if any(match_hit(hit, e) for e in expected):
            return rank, hit.label
    return None, ""


def _trunc(s: str, width: int) -> str:
    return s if len(s) <= width else s[: width - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser(description="MediLaw RAG retrieval 골든셋 평가")
    ap.add_argument("--golden", default=str(ROOT / "scripts" / "golden_set.json"),
                    help="골든셋 JSON 경로 (기본: scripts/golden_set.json)")
    ap.add_argument("--top-k", type=int, default=8, help="검색 top-k (기본 8)")
    ap.add_argument("--min-hit8", type=float, default=None,
                    help="hit@k 최소 기준. 미달 시 exit 1 (CI 게이트용, 기본 없음)")
    ap.add_argument("--json-out", default=None,
                    help="결과를 JSON 파일로도 저장 (회귀 비교용, 선택)")
    args = ap.parse_args()

    # app.config 가 import 시 .env 를 로드하고 DB_PATH 를 읽는다.
    # (DB_PATH 환경변수를 쓰려면 이 import 전에 이미 설정돼 있어야 하며,
    #  셸에서 `DB_PATH=... python3 ...` 로 실행하면 자연히 충족된다.)
    from app.config import DB_PATH
    from app.db import has_embeddings
    from app.rag import embed_queries, hybrid_search

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    questions = golden["questions"]
    print(f"DB: {DB_PATH} | 임베딩: {'있음(hybrid)' if has_embeddings() else '없음(FTS 전용)'}"
          f" | 질문 {len(questions)}개 | top_k={args.top_k}")

    # 배치 임베딩 1회 호출(N→1) — 실패/키없음 항목은 None → 해당 질문은 FTS 전용으로 폴백.
    qvecs = embed_queries([q["question"] for q in questions])

    rows = []
    for q, qvec in zip(questions, qvecs):
        if qvec is not None:
            hits, method = hybrid_search(q["question"], top_k=args.top_k, qvec=qvec)
        else:
            hits, method = hybrid_search(q["question"], top_k=args.top_k)
        rank, matched = first_match_rank(hits, q["expected"])
        rows.append({
            "id": q["id"], "domain": q["domain"], "question": q["question"],
            "rank": rank, "matched": matched, "method": method,
            "top_labels": [h.label for h in hits[:3]],
        })

    # ---- 질문별 표 ----
    print()
    print(f"{'id':<8} {'domain':<10} {'rank':>4}  {'matched / top-1(미검출 시)':<52} question")
    print("-" * 130)
    for r in rows:
        rank_s = str(r["rank"]) if r["rank"] else "MISS"
        label = r["matched"] if r["rank"] else ("top1: " + (r["top_labels"][0] if r["top_labels"] else "-"))
        print(f"{r['id']:<8} {_trunc(r['domain'], 10):<10} {rank_s:>4}  "
              f"{_trunc(label, 50):<52} {_trunc(r['question'], 44)}")

    # ---- 요약 ----
    n = len(rows)
    hit3 = sum(1 for r in rows if r["rank"] and r["rank"] <= 3) / n
    hitk = sum(1 for r in rows if r["rank"]) / n
    mrr = sum(1.0 / r["rank"] for r in rows if r["rank"]) / n
    print("-" * 130)
    print(f"전체 {n}문항 | hit@3 = {hit3:.3f} | hit@{args.top_k} = {hitk:.3f} | MRR = {mrr:.3f}")

    # 도메인별
    domains: dict[str, list[dict]] = {}
    for r in rows:
        domains.setdefault(r["domain"], []).append(r)
    for d, rs in domains.items():
        dn = len(rs)
        d_hitk = sum(1 for r in rs if r["rank"]) / dn
        d_mrr = sum(1.0 / r["rank"] for r in rs if r["rank"]) / dn
        misses = [r["id"] for r in rs if not r["rank"]]
        print(f"  {d:<12} n={dn:>2}  hit@{args.top_k}={d_hitk:.2f}  MRR={d_mrr:.2f}"
              + (f"  MISS: {', '.join(misses)}" if misses else ""))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "top_k": args.top_k, "n": n,
            "hit@3": round(hit3, 4), f"hit@{args.top_k}": round(hitk, 4), "mrr": round(mrr, 4),
            "rows": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 저장: {args.json_out}")

    if args.min_hit8 is not None and hitk < args.min_hit8:
        print(f"FAIL: hit@{args.top_k} {hitk:.3f} < 기준 {args.min_hit8}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

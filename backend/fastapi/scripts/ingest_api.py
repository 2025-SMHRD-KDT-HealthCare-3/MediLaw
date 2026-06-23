"""국가법령정보 공동활용 Open API → medilaw.db 코퍼스 확장 (법령 + 판례).

코퍼스를 "더 늘리는" 용도. 누적(idempotent):
  - 법령: law_id 기준 upsert (다시 받으면 갱신)
  - 판례: seq_no(판례일련번호)/case_no 기준 중복 스킵 (새 것만 추가)
적재 후 FTS를 rebuild 하고, 이어서 scripts/build_embeddings.py 를 incremental 모드로
실행하면 새로 추가된 행만 임베딩되어 벡터 저장소가 함께 커진다.

인증: 환경변수 LAW_OC (기본 'H-Lab'). JSON만. 한글 query는 URL 인코딩.
      ※ 법제처 OC 키는 호출 IP/도메인 등록이 되어 있어야 응답함(미등록 시 HTML 에러).

대상(target):
  law    4대 법령 본문(+시행령/규칙)        → statutes/articles upsert
  prec   판례                              → cases (seq_no/case_no dedup)
  admrul 행정규칙(고시·훈령·예규·지침)       → statutes/articles (trust_grade B)
  expc   법령해석례                         → documents(interpretation)
  ppc    개인정보보호위원회 결정문            → documents(decision)
  all    위 전부

사용법:
  python scripts/ingest_api.py --target law
  python scripts/ingest_api.py --target prec --max 200
  python scripts/ingest_api.py --target expc --max 100
  python scripts/ingest_api.py --target ppc  --query "민감정보" --max 50
  python scripts/ingest_api.py --target all  --max 100
"""
import argparse
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request

OC = os.environ.get("LAW_OC", "H-Lab")
BASE = "https://www.law.go.kr/DRF"

# 4대 법령(본법) + 시행령/시행규칙 자동 탐색
BASE_LAWS = [
    "의료법",
    "개인정보 보호법",
    "생명윤리 및 안전에 관한 법률",
    "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
]
VARIANTS = ["", " 시행령", " 시행규칙"]

# 판례 검색 기본 질의(의료 도메인). --query 로 단일 지정 가능.
PREC_QUERIES = [
    "의료법", "무면허 의료행위", "의료광고", "진료기록", "의료과실",
    "개인정보 유출", "민감정보", "생명윤리", "정보통신망",
]

_TAG_RE = re.compile(r"<[^>]+>")


def as_list(x):
    """API는 항목 1개면 list 대신 dict/단일값 → 항상 list로 정규화."""
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]


def strip_html(s: str) -> str:
    return _TAG_RE.sub("", s or "").replace("&nbsp;", " ").strip()


def norm_date(s: str) -> str:
    """'2021. 07. 15' / '20210715' / '2021.7.15' → '2021-07-15'."""
    digits = re.sub(r"\D", "", s or "")
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return s or ""


def call(path, **params):
    """DRF JSON 호출 (URL 인코딩 + 재시도)."""
    params.setdefault("OC", OC)
    params.setdefault("type", "JSON")
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                raw = r.read().decode("utf-8", "ignore")
            if raw.lstrip().startswith("<"):
                raise RuntimeError("HTML 응답(OC 미등록/미신청 또는 오류)")
            return json.loads(raw) if raw.strip() else {}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5)


# ===================== 법령(law) =====================
def find_current_law(name: str):
    d = call("lawSearch.do", target="law", query=name, display=50)
    laws = as_list(d.get("LawSearch", {}).get("law", []))
    for L in laws:
        if L.get("법령명한글") == name and L.get("현행연혁코드") == "현행":
            url = "https://www.law.go.kr/법령/" + urllib.parse.quote(name)
            return L["법령일련번호"], url
    return None


def assemble_content(unit: dict) -> str:
    parts = [unit.get("조문내용", "").strip()]
    for h in as_list(unit.get("항")):
        if not isinstance(h, dict):
            continue
        if (h.get("항내용") or "").strip():
            parts.append(h["항내용"].strip())
        for ho in as_list(h.get("호")):
            if isinstance(ho, dict) and (ho.get("호내용") or "").strip():
                parts.append(ho["호내용"].strip())
    return "\n".join(p for p in parts if p)


def fetch_law(mst: str):
    d = call("lawService.do", target="law", MST=mst).get("법령", {})
    bi = d.get("기본정보", {})

    def field(v):
        return v.get("content") if isinstance(v, dict) else (v or "")

    meta = {
        "law_id": bi.get("법령ID", ""),
        "name": bi.get("법령명_한글", ""),
        "kind": field(bi.get("법종구분", "")),
        "region_sido": field(bi.get("소관부처", "")),
        "promulgated_on": str(bi.get("공포일자", "")),
        "effective_from": str(bi.get("시행일자", "")),
        "estrev_label": bi.get("제개정구분", ""),
    }
    rows = []
    for u in as_list(d.get("조문", {}).get("조문단위", [])):
        if not isinstance(u, dict) or u.get("조문여부") != "조문":
            continue
        content = assemble_content(u)
        if content:
            rows.append((u.get("조문번호", ""), u.get("조문제목", ""), content))
    return meta, rows


def ingest_laws(conn):
    total = 0
    for base in BASE_LAWS:
        for v in VARIANTS:
            name = base + v
            found = find_current_law(name)
            if not found:
                continue
            mst, url = found
            meta, rows = fetch_law(mst)
            if not meta.get("name"):
                continue
            conn.execute(
                """INSERT INTO statutes
                   (law_id,name,kind,region_sido,promulgated_on,effective_from,source_url,trust_grade,estrev_label)
                   VALUES (:law_id,:name,:kind,:sido,:prom,:eff,:url,'법령',:est)
                   ON CONFLICT(law_id) DO UPDATE SET
                     effective_from=excluded.effective_from,
                     promulgated_on=excluded.promulgated_on,
                     source_url=excluded.source_url,
                     estrev_label=excluded.estrev_label""",
                {"law_id": meta["law_id"], "name": meta["name"], "kind": meta["kind"],
                 "sido": meta["region_sido"], "prom": meta["promulgated_on"],
                 "eff": meta["effective_from"], "url": url, "est": meta["estrev_label"]},
            )
            sid = conn.execute("SELECT id FROM statutes WHERE law_id=?", (meta["law_id"],)).fetchone()[0]
            conn.execute("DELETE FROM articles WHERE statute_id=?", (sid,))
            conn.executemany(
                "INSERT INTO articles (statute_id,article_no,article_title,content) VALUES (?,?,?,?)",
                [(sid, a, t, c) for a, t, c in rows],
            )
            conn.commit()
            total += len(rows)
            print(f"  ✅ {meta['name']:35s} 조문 {len(rows):>4}개 (시행 {meta['effective_from']})")
            time.sleep(0.3)
    print("[articles FTS rebuild...]")
    conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
    conn.commit()
    print(f"=== 법령 적재 조문 합계: {total:,} ===")


# ===================== 판례(prec) =====================
def search_prec(query: str, max_n: int):
    """판례 목록 검색 → 판례정보일련번호 리스트.
    dedup 키(저장되는 seq_no=판례정보일련번호)와 동일 필드를 ID로 채택해야
    재실행 시 사전 스킵(pid in seqs)이 동작한다. 따라서 검색단계도
    판례정보일련번호를 우선 사용(없을 때만 판례일련번호로 폴백)."""
    ids, page = [], 1
    while len(ids) < max_n:
        d = call("lawSearch.do", target="prec", query=query, display=100, page=page)
        items = as_list(d.get("PrecSearch", {}).get("prec", []))
        if not items:
            break
        for it in items:
            sid = it.get("판례정보일련번호") or it.get("판례일련번호")
            if sid:
                ids.append(str(sid))
        page += 1
        if len(items) < 100:
            break
        time.sleep(0.2)
    return ids[:max_n]


def fetch_prec(prec_id: str):
    """판례 본문 조회 → cases 행 dict. prec_id=판례정보일련번호(검색·dedup과 동일 필드).
    seq_no는 상세응답의 판례정보일련번호(없으면 prec_id)로 저장 → 검색·상세·dedup 정합.
    응답 필드명은 환경에서 1회 검증 권장."""
    d = call("lawService.do", target="prec", ID=prec_id)
    p = d.get("PrecService") or d.get("판례") or {}
    if not isinstance(p, dict) or not p:
        return None
    return {
        "seq_no": str(p.get("판례정보일련번호") or prec_id),
        "case_no": (p.get("사건번호") or "").strip(),
        "case_name": (p.get("사건명") or "").strip(),
        "court": (p.get("법원명") or "").strip(),
        "court_level": (p.get("법원종류명") or "").strip(),
        "case_type": (p.get("사건종류명") or "").strip(),
        "date": norm_date(p.get("선고일자") or ""),
        "summary": strip_html(p.get("판결요지") or ""),
        "issues": strip_html(p.get("판시사항") or ""),
        "ref_text": strip_html(p.get("참조조문") or ""),
        "body": strip_html(p.get("판례내용") or ""),
        "source_url": f"https://www.law.go.kr/판례/({prec_id})",
    }


def _existing_keys(conn):
    seqs = {r[0] for r in conn.execute("SELECT seq_no FROM cases WHERE seq_no IS NOT NULL")}
    nos = {r[0] for r in conn.execute("SELECT case_no FROM cases WHERE case_no IS NOT NULL AND case_no!=''")}
    return seqs, nos


def ingest_prec(conn, queries, max_n):
    seqs, nos = _existing_keys(conn)
    added = 0
    for q in queries:
        ids = search_prec(q, max_n)
        print(f"  [{q}] 검색 {len(ids)}건")
        for pid in ids:
            if pid in seqs:
                continue
            row = fetch_prec(pid)
            if not row or (not row["case_name"] and not row["body"]):
                continue
            if row["seq_no"] in seqs or (row["case_no"] and row["case_no"] in nos):
                continue
            conn.execute(
                """INSERT INTO cases
                   (seq_no,case_no,case_name,court,court_level,case_type,date,summary,issues,ref_text,body,source_url)
                   VALUES (:seq_no,:case_no,:case_name,:court,:court_level,:case_type,:date,:summary,:issues,:ref_text,:body,:source_url)""",
                row,
            )
            seqs.add(row["seq_no"])
            if row["case_no"]:
                nos.add(row["case_no"])
            added += 1
            if added % 50 == 0:
                conn.commit()
                print(f"    ...누적 추가 {added}")
            time.sleep(0.2)
    conn.commit()
    print("[cases FTS rebuild...]")
    conn.execute("INSERT INTO cases_fts(cases_fts) VALUES('rebuild')")
    conn.commit()
    print(f"=== 판례 신규 추가: {added:,}건 (총 {conn.execute('SELECT COUNT(*) FROM cases').fetchone()[0]:,}) ===")


# ===================== documents (해석례 expc / 결정문 ppc) =====================
# 법령도 판례도 아닌 문서 → 별도 테이블. source_type: interpretation(해석례)/decision(결정문)
DOMAIN_QUERIES = ["의료법", "개인정보", "민감정보", "생명윤리", "정보통신망", "의료광고", "진료기록"]
PPC_QUERIES = ["개인정보", "민감정보", "건강정보", "진료기록", "가명정보"]


def ensure_documents(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            doc_type TEXT, doc_uid TEXT,
            title TEXT, agency TEXT, date TEXT,
            body TEXT, source_url TEXT,
            UNIQUE(doc_type, doc_uid))"""
    )
    conn.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            title, body, content=documents, content_rowid=id, tokenize='unicode61')"""
    )
    conn.commit()


def _doc_exists(conn, doc_type, uid):
    return conn.execute(
        "SELECT 1 FROM documents WHERE doc_type=? AND doc_uid=?", (doc_type, uid)
    ).fetchone() is not None


def _search_uids(target, root_key, item_key, uid_key, query, max_n):
    uids, page = [], 1
    while len(uids) < max_n:
        d = call("lawSearch.do", target=target, query=query, display=100, page=page)
        items = as_list(d.get(root_key, {}).get(item_key, []))
        if not items:
            break
        for it in items:
            u = it.get(uid_key)
            if u:
                uids.append(str(u))
        if len(items) < 100:
            break
        page += 1
        time.sleep(0.2)
    return uids[:max_n]


def _ingest_documents(conn, doc_type, target, root, uid_key, extract, queries, max_n, label):
    """expc/ppc 공통 수집 루프. extract(detail_json)->(title,agency,date,body,url)."""
    ensure_documents(conn)
    added = 0
    for q in queries:
        uids = _search_uids(target, root, target, uid_key, q, max_n)
        print(f"  [{target}:{q}] 검색 {len(uids)}건")
        for uid in uids:
            if _doc_exists(conn, doc_type, uid):
                continue
            det = call("lawService.do", target=target, ID=uid)
            parsed = extract(det, uid)
            if not parsed:
                continue
            title, agency, date, body, url = parsed
            if not (title or body):
                continue
            conn.execute(
                """INSERT OR IGNORE INTO documents
                   (doc_type,doc_uid,title,agency,date,body,source_url) VALUES (?,?,?,?,?,?,?)""",
                (doc_type, uid, title, agency, date, body, url),
            )
            added += 1
            if added % 50 == 0:
                conn.commit()
                print(f"    ...누적 {added}")
            time.sleep(0.2)
    conn.commit()
    conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
    conn.commit()
    print(f"=== {label} 신규: {added:,}건 (총 documents {conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]:,}) ===")


def _expc_extract(det, uid):
    b = det.get("ExpcService", {})
    if not isinstance(b, dict) or not b:
        return None
    body = "\n".join(filter(None, [
        strip_html(b.get("질의요지", "")), strip_html(b.get("회답", "")), strip_html(b.get("이유", "")),
    ]))
    return (strip_html(b.get("안건명", "")), strip_html(b.get("해석기관명", "")),
            norm_date(b.get("해석일자", "")), body,
            f"https://www.law.go.kr/법령해석례/({uid})")


def _ppc_extract(det, uid):
    b = det.get("PpcService", {}).get("의결서", {})
    if not isinstance(b, dict) or not b:
        return None
    body = "\n".join(filter(None, [
        strip_html(b.get("결정요지", "")), strip_html(b.get("주문", "")),
        strip_html(b.get("주요내용", "")), strip_html(b.get("이유", "")),
    ]))
    return (strip_html(b.get("안건명", "")), strip_html(b.get("기관명", "")),
            norm_date(b.get("의결일자") or b.get("의결연월일", "")), body,
            f"https://www.law.go.kr/LSW/ppcDecInfoP.do?ppcSeq={uid}")


def ingest_expc(conn, queries, max_n):
    _ingest_documents(conn, "interpretation", "expc", "Expc", "법령해석례일련번호",
                      _expc_extract, queries, max_n, "법령해석례")


def ingest_ppc(conn, queries, max_n):
    _ingest_documents(conn, "decision", "ppc", "Ppc", "결정문일련번호",
                      _ppc_extract, queries, max_n, "개인정보위 결정문")


# ===================== 행정규칙(admrul) → statutes + articles =====================
_ART_HEAD_RE = re.compile(r"제(\d+(?:의\d+)?)조(?:\(([^)]*)\))?")


def ingest_admrul(conn, queries, max_n):
    added_rules = added_arts = 0
    for q in queries:
        metas, page = [], 1
        while len(metas) < max_n:
            d = call("lawSearch.do", target="admrul", query=q, display=100, page=page)
            items = as_list(d.get("AdmRulSearch", {}).get("admrul", []))
            if not items:
                break
            metas += items
            if len(items) < 100:
                break
            page += 1
            time.sleep(0.2)
        metas = metas[:max_n]
        print(f"  [admrul:{q}] 검색 {len(metas)}건")
        for meta in metas:
            rid = str(meta.get("행정규칙일련번호") or "")
            if not rid:
                continue
            law_id = "ADMRUL-" + rid
            if conn.execute("SELECT 1 FROM statutes WHERE law_id=?", (law_id,)).fetchone():
                continue
            d = call("lawService.do", target="admrul", ID=rid).get("AdmRulService", {})
            if not isinstance(d, dict) or not d:
                continue
            bi = d.get("행정규칙기본정보", {}) if isinstance(d.get("행정규칙기본정보"), dict) else {}
            name = bi.get("행정규칙명") or meta.get("행정규칙명", "")
            conn.execute(
                """INSERT INTO statutes
                   (law_id,name,kind,region_sido,promulgated_on,effective_from,source_url,trust_grade)
                   VALUES (?,?,?,?,?,?,?, 'B')""",
                (law_id, name,
                 bi.get("행정규칙종류") or meta.get("행정규칙종류", ""),
                 bi.get("담당부서기관명") or meta.get("소관부처명", ""),
                 norm_date(bi.get("발령일자") or meta.get("발령일자", "")),
                 norm_date(meta.get("시행일자", "")),
                 "https://www.law.go.kr/행정규칙/" + urllib.parse.quote(name)),
            )
            sid = conn.execute("SELECT id FROM statutes WHERE law_id=?", (law_id,)).fetchone()[0]
            rows = []
            for s in as_list(d.get("조문내용")):
                if not isinstance(s, str):
                    continue
                txt = strip_html(s).strip()
                if not txt:
                    continue
                m = _ART_HEAD_RE.match(txt)
                rows.append((m.group(1) if m else "", (m.group(2) if m else "") or "", txt))
            if rows:
                conn.executemany(
                    "INSERT INTO articles (statute_id,article_no,article_title,content) VALUES (?,?,?,?)",
                    [(sid, a, t, c) for a, t, c in rows],
                )
                added_arts += len(rows)
            added_rules += 1
            conn.commit()
            time.sleep(0.2)
    conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
    conn.commit()
    print(f"=== 행정규칙 신규: {added_rules:,}개 규칙, {added_arts:,}조 ===")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["law", "prec", "expc", "admrul", "ppc", "all"], required=True)
    ap.add_argument("--db", default="data/medilaw.db")
    ap.add_argument("--query", help="단일 검색어 (생략 시 도메인 기본 질의)")
    ap.add_argument("--max", type=int, default=200, help="질의별 최대 건수")
    args = ap.parse_args()

    q = [args.query] if args.query else None
    t = args.target
    conn = sqlite3.connect(args.db)
    if t in ("law", "all"):
        ingest_laws(conn)
    if t in ("prec", "all"):
        ingest_prec(conn, q or PREC_QUERIES, args.max)
    if t in ("expc", "all"):
        ingest_expc(conn, q or DOMAIN_QUERIES, args.max)
    if t in ("admrul", "all"):
        ingest_admrul(conn, q or DOMAIN_QUERIES, args.max)
    if t in ("ppc", "all"):
        ingest_ppc(conn, q or PPC_QUERIES, args.max)
    conn.close()
    print("\n다음: 새 데이터 임베딩 →  python scripts/build_embeddings.py  (MODE=incremental 기본)")


if __name__ == "__main__":
    main()

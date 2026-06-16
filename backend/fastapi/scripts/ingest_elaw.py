"""법제처 영문법령 Open API(target=elaw) → medilaw.db `articles_en` 적재.

영어 입력 기능에서 **법령 인용을 공식 영문**으로 보여주기 위한 캐시.
한국어 코퍼스(articles)와 (법령명_한글, 조문번호)로 매칭된다.

흐름: lawSearch(elaw)로 법령명→MST → lawService(elaw)로 영문 조문 본문 →
      Jo[].joYn=='Y' 조문만 (law_name_ko, article_no) 키로 upsert(법령 단위 교체).

대상: 4대 법령 + 시행령/규칙(공식 영문판이 있는 것만 자동 채택).
인증: 환경변수 LAW_OC (기본 'H-Lab'). 한국어 코퍼스용 ingest_api.py 와 같은 키.

사용법:
  python scripts/ingest_elaw.py
  python scripts/ingest_elaw.py --db data/medilaw.db
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

# 한국어 코퍼스(ingest_api.py)와 동일 — 영문판 매칭 대상
BASE_LAWS = [
    "의료법",
    "개인정보 보호법",
    "생명윤리 및 안전에 관한 법률",
    "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
]
VARIANTS = ["", " 시행령", " 시행규칙"]

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return _TAG_RE.sub("", s or "").replace("&nbsp;", " ").strip()


def as_list(x):
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]


def call(path, **params):
    """DRF JSON 호출 (URL 인코딩 + 재시도). HTML 응답이면 OC 미등록."""
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
            time.sleep(0.6)
    return {}


def norm_article_no(jo_no: str, jo_br_no: str) -> str:
    """elaw joNo/joBrNo → 한국어 코퍼스 article_no 포맷('27' 또는 '27의2')."""
    try:
        n = str(int(jo_no))
    except (TypeError, ValueError):
        return (jo_no or "").lstrip("0") or jo_no or ""
    br = (jo_br_no or "00").strip()
    if br not in ("", "0", "00"):
        return f"{n}의{int(br)}"
    return n


def find_english_law(name: str):
    """영문법령 목록에서 정확명 매칭 → (MST, 영문법령명, 시행일). 없으면 None.

    영문판은 한국어 최신 개정보다 늦어 현행연혁코드가 '연혁'인 경우가 많음
    (예: 의료법). 따라서 현행여부로 거르지 않고 정확명 매칭 중 시행일자 최신본 채택.
    """
    d = call("lawSearch.do", target="elaw", query=name, display=50, search=1)
    matches = [
        L for L in as_list(d.get("LawSearch", {}).get("law", []))
        if strip_html(L.get("법령명한글", "")) == name
    ]
    if not matches:
        return None
    best = max(matches, key=lambda L: re.sub(r"\D", "", L.get("시행일자", "") or ""))
    return best.get("법령일련번호"), best.get("법령명영문", ""), best.get("시행일자", "")


def fetch_english_articles(mst: str):
    """lawService(elaw) → [(article_no, title_en, body_en)] (실제 조문만)."""
    d = call("lawService.do", target="elaw", MST=mst)
    rows = []
    for jo in as_list(d.get("Law", {}).get("JoSection", {}).get("Jo", [])):
        if not isinstance(jo, dict) or jo.get("joYn") != "Y":
            continue  # joYn=N 은 장/절 제목
        body = strip_html(jo.get("joCts", ""))
        if not body:
            continue
        rows.append((
            norm_article_no(jo.get("joNo", ""), jo.get("joBrNo", "")),
            strip_html(jo.get("joTtl", "")),
            body,
        ))
    return rows


def ensure_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS articles_en (
            id INTEGER PRIMARY KEY,
            law_name_ko TEXT NOT NULL,
            law_name_en TEXT,
            article_no  TEXT NOT NULL,
            title_en    TEXT,
            body_en     TEXT,
            mst         TEXT,
            eng_effective TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_en ON articles_en(law_name_ko, article_no)"
    )
    conn.commit()


def ingest(conn):
    ensure_table(conn)
    total = 0
    for base in BASE_LAWS:
        for v in VARIANTS:
            name = base + v
            found = find_english_law(name)
            if not found:
                continue  # 공식 영문판 없음(예: 일부 시행규칙)
            mst, name_en, eff = found
            rows = fetch_english_articles(mst)
            if not rows:
                continue
            conn.execute("DELETE FROM articles_en WHERE law_name_ko=?", (name,))
            conn.executemany(
                """INSERT INTO articles_en
                   (law_name_ko, law_name_en, article_no, title_en, body_en, mst, eng_effective)
                   VALUES (?,?,?,?,?,?,?)""",
                [(name, name_en, a, t, b, str(mst), eff) for a, t, b in rows],
            )
            conn.commit()
            total += len(rows)
            print(f"  ✅ {name:38s} → {name_en[:45]:45s} 조문 {len(rows):>4} (시행 {eff})")
            time.sleep(0.3)
    cnt = conn.execute("SELECT COUNT(*) FROM articles_en").fetchone()[0]
    print(f"=== 영문 조문 적재 완료: 이번 {total:,} / 총 articles_en {cnt:,} ===")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_PATH", "data/medilaw.db"))
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    try:
        ingest(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

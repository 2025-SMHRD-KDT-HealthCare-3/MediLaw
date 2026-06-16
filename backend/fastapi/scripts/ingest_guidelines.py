"""보건복지부 게시판(가이드라인/지침/고시) → medilaw.db documents(doc_type='guideline').

법제처 API에 없는 보건복지부 가이드라인을 게시판 첨부파일(PDF/HWPX)에서 추출해 적재한다.
RAG 파이프라인(documents_fts + 임베딩)에 그대로 들어가 retrieve의 source_type='guideline'로 검색됨.

게시판: https://www.mohw.go.kr/board.es?mid=a10409020000&bid=0026
  목록   board.es?...&nPage=N        → 게시물 (list_no, 제목)
  상세   board.es?...&act=view&list_no=L
  첨부   boardDownload.es?bid=0026&list_no=L&seq=S

지원 형식: .pdf(pypdf), .hwpx/.docx(zip+xml), .hwp(구형 OLE — PrvText 스트림). 스캔본(이미지)은 OCR 필요(미지원).

사용법:
  # 통합검색(여러 게시판 교차) — 권장. 원하는 가이드라인 제목으로 검색
  python scripts/ingest_guidelines.py --search "의료기관 개인정보보호 가이드라인,비의료 건강관리서비스,유전자검사 가이드라인"
  # board 0026 제목 크롤
  python scripts/ingest_guidelines.py --keyword 가이드라인 --pages 30
  # 특정 게시물(bid=0026)만
  python scripts/ingest_guidelines.py --list_no 1490826
"""
import argparse
import html as htmlmod
import io
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import zipfile

BID = "0026"
MID = "a10409020000"
BASE = "https://www.mohw.go.kr"
HDR = {"User-Agent": "Mozilla/5.0"}
_TAG_RE = re.compile(r"<[^>]+>")


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=HDR)
    return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")


def get_bytes(url: str):
    req = urllib.request.Request(url, headers=HDR)
    r = urllib.request.urlopen(req, timeout=40)
    return r.read(), r.headers.get("Content-Disposition", "")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", s or "")).strip()


# ---------- 목록 크롤 ----------
def list_posts(pages: int, keyword: str):
    """nPage 1..pages 훑어 (list_no, title) 중 keyword 포함만 반환."""
    out = []
    for p in range(1, pages + 1):
        url = f"{BASE}/board.es?mid={MID}&bid={BID}&nPage={p}"
        try:
            h = get(url)
        except Exception as e:
            print(f"  [page {p}] 실패: {e}")
            continue
        pairs = re.findall(r'href="[^"]*list_no=(\d+)[^"]*"[^>]*>(.*?)</a>', h, re.S)
        for lno, title in pairs:
            t = htmlmod.unescape(clean(title))
            if keyword in t:
                out.append((lno, t))
        time.sleep(0.2)
    # 중복 list_no 제거
    seen, uniq = set(), []
    for lno, t in out:
        if lno not in seen:
            seen.add(lno)
            uniq.append((lno, t))
    return uniq


# ---------- 통합검색 (여러 게시판 교차) ----------
def search_posts(term: str, max_n: int):
    """React 통합검색 → [(bid, mid, list_no, title)]. 게시판(bid)이 글마다 다를 수 있음."""
    url = f"{BASE}/react/search/search.jsp?searchTerm=" + urllib.parse.quote(term)
    try:
        h = get(url)
    except Exception as e:
        print(f"  [검색 실패] {e}")
        return []
    pairs = re.findall(r'href="([^"]*board\.es[^"]*list_no=\d+[^"]*)"[^>]*>(.*?)</a>', h, re.S)
    out, seen = [], set()
    for href, t in pairs:
        href = htmlmod.unescape(href)
        bid = re.search(r"bid=(\d+)", href)
        lno = re.search(r"list_no=(\d+)", href)
        mid = re.search(r"mid=(\w+)", href)
        if not (bid and lno and mid):
            continue
        title = htmlmod.unescape(clean(t)).split('">')[-1].strip()  # 검색 하이라이트 잔여 제거
        key = (bid.group(1), lno.group(1))
        if key in seen:
            continue
        seen.add(key)
        out.append((bid.group(1), mid.group(1), lno.group(1), title))
    return out[:max_n]


# ---------- 상세 → 첨부 ----------
def attachments(bid: str, mid: str, list_no: str):
    """상세 페이지에서 첨부 seq 목록 + 등록일 + 상세URL."""
    url = f"{BASE}/board.es?mid={mid}&bid={bid}&act=view&list_no={list_no}"
    h = get(url)
    seqs = re.findall(rf"/boardDownload\.es\?bid={bid}&amp;list_no={list_no}&amp;seq=(\d+)", h)
    m = re.search(r"(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})", h)
    date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""
    return sorted(set(seqs), key=int), date, url


# ---------- 첨부 텍스트 추출 ----------
def extract_text(data: bytes, fname: str) -> str:
    if data[:4] == b"%PDF":
        try:
            import pypdf

            r = pypdf.PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception as e:
            print(f"    [pdf 추출 실패] {e}")
            return ""
    if data[:2] == b"PK":  # zip 계열: hwpx / docx
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = z.namelist()
            secs = [n for n in names if re.search(r"Contents/section\d+\.xml", n)]
            if secs:  # hwpx
                return clean(" ".join(z.read(s).decode("utf-8", "ignore") for s in sorted(secs)))
            if "word/document.xml" in names:  # docx
                return clean(z.read("word/document.xml").decode("utf-8", "ignore"))
            if "Preview/PrvText.txt" in names:  # hwpx 텍스트 미리보기 폴백
                return z.read("Preview/PrvText.txt").decode("utf-8", "ignore").strip()
        except Exception as e:
            print(f"    [zip 추출 실패] {e}")
            return ""
    if data[:4] == b"\xd0\xcf\x11\xe0":  # 구형 HWP (OLE 복합문서)
        return _extract_hwp_ole(data)
    return ""


def _extract_hwp_ole(data: bytes) -> str:
    """구형 .hwp(OLE): PrvText 스트림(UTF-16LE 본문 미리보기)을 우선 사용.
    실패 시 BodyText 섹션(zlib 압축 레코드)에서 텍스트 복원 시도."""
    try:
        import olefile
    except ImportError:
        print("    [hwp: olefile 미설치 — 건너뜀]")
        return ""
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as e:
        print(f"    [hwp OLE 열기 실패] {e}")
        return ""
    try:
        if ole.exists("PrvText"):
            txt = ole.openstream("PrvText").read().decode("utf-16-le", "ignore")
            if txt.strip():
                return re.sub(r"\s+\n", "\n", txt).strip()
        # 폴백: BodyText/Section* (zlib raw) → 한글 텍스트만 추출
        import struct, zlib

        parts = []
        for entry in ole.listdir():
            if len(entry) >= 2 and entry[0] == "BodyText" and entry[1].startswith("Section"):
                raw = ole.openstream(entry).read()
                try:
                    raw = zlib.decompress(raw, -15)
                except Exception:
                    pass
                # 레코드 파싱 대신, UTF-16LE로 보이는 한글 구간만 긁기(근사)
                try:
                    s = raw.decode("utf-16-le", "ignore")
                    s = "".join(ch for ch in s if ch == "\n" or ch == " " or "가" <= ch <= "힣"
                                or "A" <= ch <= "z" or ch.isdigit() or ch in ".,()[]·-")
                    if len(s.strip()) > 30:
                        parts.append(s)
                except Exception:
                    pass
        return re.sub(r"\s+", " ", " ".join(parts)).strip()
    except Exception as e:
        print(f"    [hwp 추출 실패] {e}")
        return ""
    finally:
        ole.close()


def ensure_documents(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY, doc_type TEXT, doc_uid TEXT,
            title TEXT, agency TEXT, date TEXT, body TEXT, source_url TEXT,
            UNIQUE(doc_type, doc_uid))"""
    )
    conn.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            title, body, content=documents, content_rowid=id, tokenize='unicode61')"""
    )
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/medilaw.db")
    ap.add_argument("--search", help="통합검색어(쉼표구분). 여러 게시판 교차 검색 — 권장")
    ap.add_argument("--keyword", default="가이드라인", help="board 크롤 시 제목 필터")
    ap.add_argument("--pages", type=int, default=20, help="board 크롤 페이지 수")
    ap.add_argument("--list_no", help="특정 게시물 list_no (bid=0026 가정, 쉼표구분)")
    ap.add_argument("--max", type=int, default=50, help="검색어/모드별 최대 게시물 수")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    ensure_documents(conn)

    # posts: (bid, mid, list_no, title)
    if args.search:
        posts = []
        for term in args.search.split(","):
            posts += search_posts(term.strip(), args.max)
    elif args.list_no:
        posts = [(BID, MID, l.strip(), "") for l in args.list_no.split(",") if l.strip()]
    else:
        posts = [(BID, MID, l, t) for l, t in list_posts(args.pages, args.keyword)[: args.max]]
    print(f"대상 게시물 {len(posts)}건")

    added = 0
    for bid, mid, list_no, title in posts:
        try:
            seqs, date, src = attachments(bid, mid, list_no)
        except Exception as e:
            print(f"  [list_no {list_no}] 상세 실패: {e}")
            continue
        if not seqs:
            continue
        for seq in seqs:
            uid = f"{bid}-{list_no}-{seq}"
            if conn.execute("SELECT 1 FROM documents WHERE doc_type='guideline' AND doc_uid=?", (uid,)).fetchone():
                continue
            try:
                data, cd = get_bytes(f"{BASE}/boardDownload.es?bid={bid}&list_no={list_no}&seq={seq}")
            except Exception as e:
                print(f"  [{uid}] 다운로드 실패: {e}")
                continue
            fname = ""
            m = re.search(r'filename="?([^"]+)"?', cd or "")
            if m:
                fname = urllib.parse.unquote(m.group(1))
            body = extract_text(data, fname)
            if not body or len(body) < 50:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO documents
                   (doc_type,doc_uid,title,agency,date,body,source_url) VALUES ('guideline',?,?,?,?,?,?)""",
                (uid, title or fname, "보건복지부", date, body, src),
            )
            added += 1
            print(f"  + {uid} [{len(body):,}자] {(title or fname)[:45]}")
            time.sleep(0.3)
        conn.commit()

    conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM documents WHERE doc_type='guideline'").fetchone()[0]
    conn.close()
    print(f"\n=== 가이드라인 신규 {added}건 (총 guideline {total}) ===")
    print("다음: python scripts/build_embeddings.py  (MODE=incremental)")


if __name__ == "__main__":
    main()

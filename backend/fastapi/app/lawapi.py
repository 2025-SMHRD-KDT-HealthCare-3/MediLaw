"""법제처 국가법령정보 공동활용 DRF 클라이언트 — 법령 개정 현황(연혁/버전) 조회.

기획서 핵심기능 ⑤ 법령 개정 현황 대시보드의 데이터 소스.
 - fetch_versions(name)        : 한 법령의 모든 버전(시행예정/현행/연혁) 타임라인
 - fetch_version_detail(mst,ef): (MST, 시행일자efYd)로 그 버전의 조문/제개정이유

OC 키(config.LAW_OC)는 호출 IP/도메인이 등록돼 있어야 응답함(미등록 시 HTML 에러).
연혁·현행·시행예정 버전은 lawService.do?target=eflaw 에 MST 와 efYd 가 모두 필요함.
"""
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from app.config import LAW_OC

BASE = "https://www.law.go.kr/DRF"
_TAG_RE = re.compile(r"<[^>]+>")


class LawApiError(RuntimeError):
    """법제처 API 호출 실패(OC 미등록·네트워크 등)."""


def as_list(x):
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def call(path: str, **params):
    """DRF JSON 호출 (URL 인코딩 + 재시도). HTML 응답이면 LawApiError."""
    params.setdefault("OC", LAW_OC)
    params.setdefault("type", "JSON")
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                raw = r.read().decode("utf-8", "ignore")
            if raw.lstrip().startswith("<"):
                raise LawApiError("법제처 API HTML 응답(OC 미등록/미신청 또는 오류)")
            return json.loads(raw) if raw.strip() else {}
        except LawApiError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.2)
    raise LawApiError(f"법제처 API 호출 실패: {last}")


def assemble_content(unit: dict) -> str:
    """조문단위 dict → 조문+항+호 본문 텍스트."""
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


def _flatten_text(x) -> str:
    """중첩 리스트/문자열(제개정이유내용 등)을 줄바꿈 텍스트로."""
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, list):
        return "\n".join(t for t in (_flatten_text(i) for i in x) if t)
    return ""


def fetch_versions(name: str) -> list[dict]:
    """법령명 → 모든 버전 타임라인. 각 항목:
    {mst,name,law_id,status(시행예정|현행|연혁),effective_on,promulgated_on,
     promulgation_no,revision_type,ministry,detail_url}. (날짜는 YYYYMMDD)
    """
    d = call("lawSearch.do", target="eflaw", query=name, display=100)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for L in as_list(d.get("LawSearch", {}).get("law", [])):
        if L.get("법령명한글") != name:
            continue
        mst = str(L.get("법령일련번호", ""))
        eff = _digits(L.get("시행일자"))
        if (mst, eff) in seen:
            continue
        seen.add((mst, eff))
        out.append({
            "mst": mst,
            "name": L.get("법령명한글", ""),
            "law_id": str(L.get("법령ID", "")),
            "status": L.get("현행연혁코드", ""),
            "effective_on": eff,
            "promulgated_on": _digits(L.get("공포일자")),
            "promulgation_no": str(L.get("공포번호", "")),
            "revision_type": L.get("제개정구분명", "") or L.get("제개정구분", ""),
            "ministry": L.get("소관부처명", ""),
            "detail_url": "https://www.law.go.kr" + (L.get("법령상세링크", "") or ""),
        })
    # 시행일 내림차순(최신 먼저)
    out.sort(key=lambda r: r["effective_on"], reverse=True)
    return out


def fetch_version_detail(mst: str, effective_on: str) -> dict:
    """(MST, efYd) → {articles:{조문번호:(제목,본문)}, reason:str, effective_on, promulgated_on}."""
    d = call("lawService.do", target="eflaw", MST=mst, efYd=_digits(effective_on)).get("법령", {})
    articles: dict[str, tuple[str, str]] = {}
    for u in as_list(d.get("조문", {}).get("조문단위", [])):
        if isinstance(u, dict) and u.get("조문여부") == "조문":
            articles[str(u.get("조문번호", ""))] = (u.get("조문제목", ""), assemble_content(u))
    reason = _flatten_text((d.get("제개정이유") or {}).get("제개정이유내용"))
    bi = d.get("기본정보", {})
    return {
        "articles": articles,
        "reason": reason,
        "effective_on": _digits(bi.get("시행일자")) or _digits(effective_on),
        "promulgated_on": _digits(bi.get("공포일자")),
    }


# ───────────── 개정 현황 저장 테이블 (sync 스크립트/라우터 공용) ─────────────
def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS law_revisions (
            law_id          TEXT NOT NULL,
            name            TEXT,
            mst             TEXT NOT NULL,
            effective_on    TEXT NOT NULL,
            promulgated_on  TEXT,
            promulgation_no TEXT,
            revision_type   TEXT,
            status          TEXT,            -- 시행예정 | 현행 | 연혁
            ministry        TEXT,
            reason          TEXT DEFAULT '',
            detail_url      TEXT,
            synced_at       TEXT,
            PRIMARY KEY (law_id, mst, effective_on)
        );
        CREATE INDEX IF NOT EXISTS idx_law_rev_law ON law_revisions(law_id, effective_on);

        -- 개정 전후 조문 비교용 버전별 조문 캐시(요청 시 lazy 적재)
        CREATE TABLE IF NOT EXISTS law_revision_articles (
            law_id        TEXT NOT NULL,
            mst           TEXT NOT NULL,
            effective_on  TEXT NOT NULL,
            article_no    TEXT NOT NULL,
            article_title TEXT,
            content       TEXT,
            PRIMARY KEY (law_id, mst, effective_on, article_no)
        );
        """
    )
    conn.commit()


def has_revisions(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='law_revisions'"
    ).fetchone()
    if not row:
        return False
    return conn.execute("SELECT COUNT(*) FROM law_revisions").fetchone()[0] > 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sync_law(conn: sqlite3.Connection, name: str, with_reason: bool = True) -> list[dict]:
    """한 법령의 전체 버전 타임라인을 law_revisions 에 upsert(idempotent). 배치/폴백 공용."""
    ensure_tables(conn)
    versions = fetch_versions(name)
    if not versions:
        return []
    reason_by_mst: dict[str, str] = {}
    if with_reason:
        cur = next((v for v in versions if v["status"] == "현행"), None)
        if cur:
            try:
                reason_by_mst[cur["mst"]] = fetch_version_detail(
                    cur["mst"], cur["effective_on"]).get("reason", "")
            except LawApiError:
                pass
    now = _now_iso()
    conn.executemany(
        """INSERT INTO law_revisions
           (law_id,name,mst,effective_on,promulgated_on,promulgation_no,revision_type,
            status,ministry,reason,detail_url,synced_at)
           VALUES (:law_id,:name,:mst,:effective_on,:promulgated_on,:promulgation_no,
                   :revision_type,:status,:ministry,:reason,:detail_url,:synced_at)
           ON CONFLICT(law_id,mst,effective_on) DO UPDATE SET
             status=excluded.status, revision_type=excluded.revision_type,
             reason=CASE WHEN excluded.reason<>'' THEN excluded.reason ELSE law_revisions.reason END,
             synced_at=excluded.synced_at""",
        [{**v, "reason": reason_by_mst.get(v["mst"], ""), "synced_at": now} for v in versions],
    )
    conn.commit()
    return versions


def version_articles(conn: sqlite3.Connection, law_id: str, mst: str,
                     effective_on: str) -> dict[str, tuple[str, str]]:
    """버전 조문 {번호:(제목,본문)} — 캐시 우선, 없으면 API fetch 후 캐시."""
    ensure_tables(conn)
    efyd = _digits(effective_on)
    rows = conn.execute(
        "SELECT article_no,article_title,content FROM law_revision_articles "
        "WHERE law_id=? AND mst=? AND effective_on=?",
        (law_id, mst, efyd),
    ).fetchall()
    if rows:
        return {r[0]: (r[1], r[2]) for r in rows}
    arts = fetch_version_detail(mst, efyd)["articles"]
    if arts:
        conn.executemany(
            "INSERT OR REPLACE INTO law_revision_articles "
            "(law_id,mst,effective_on,article_no,article_title,content) VALUES (?,?,?,?,?,?)",
            [(law_id, mst, efyd, no, t, c) for no, (t, c) in arts.items()],
        )
        conn.commit()
    return arts

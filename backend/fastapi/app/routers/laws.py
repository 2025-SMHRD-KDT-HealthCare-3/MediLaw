"""기획서 핵심기능 ⑤ — 법령 개정 현황 대시보드.

법제처 국가법령정보 공동활용 데이터로 4대 법령의 개정 타임라인을 추적·제공.
 GET /v1/laws/revisions           : 대시보드 메인(법령별 현행·시행예정·연혁수)
 GET /v1/laws/{law_id}/revisions  : 한 법령 전체 개정 이력 타임라인
 GET /v1/laws/diff                : 개정 전후 조문 비교표(before/after)

배치 동기화는 scripts/sync_revisions.py(1일 1회 cron). 미동기화 시 첫 호출에서 라이브 부트스트랩.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Query

from app import lawapi
from app.auth import require_api_key
from app.config import TRACKED_LAWS
from app.db import db
from app.schemas import (
    ArticleDiff,
    LawDiffResponse,
    LawRevision,
    LawRevisionsResponse,
    LawStatus,
    LawTimelineResponse,
)

router = APIRouter(prefix="/v1/laws", tags=["법령 개정 현황 대시보드"])


def _ymd(d):
    d = re.sub(r"\D", "", str(d or ""))
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else None


def _art_sort_key(no: str):
    """조문번호 '2','2-2' 등을 자연 정렬."""
    nums = [int(x) for x in re.findall(r"\d+", no or "")]
    return (nums or [0])


def _row_to_rev(r) -> LawRevision:
    return LawRevision(
        mst=r["mst"], effective_on=_ymd(r["effective_on"]),
        promulgated_on=_ymd(r["promulgated_on"]), promulgation_no=r["promulgation_no"] or "",
        revision_type=r["revision_type"] or "", status=r["status"] or "",
        reason=r["reason"] or "", detail_url=r["detail_url"] or "",
    )


def _bootstrap_if_empty(conn):
    """미동기화면 추적 법령을 라이브로 1회 동기화(자기 부트스트랩)."""
    if lawapi.has_revisions(conn):
        return
    for name in TRACKED_LAWS:
        try:
            lawapi.sync_law(conn, name)
        except lawapi.LawApiError:
            continue


@router.get("/revisions", response_model=LawRevisionsResponse,
            dependencies=[Depends(require_api_key)])
def revisions():
    """대시보드 메인 — 추적 법령별 현행/시행예정/연혁 요약."""
    conn = db()
    lawapi.ensure_tables(conn)
    _bootstrap_if_empty(conn)
    rows = conn.execute(
        "SELECT * FROM law_revisions ORDER BY law_id, effective_on DESC"
    ).fetchall()
    if not rows:
        raise HTTPException(
            503, "법령 개정 데이터가 없습니다. scripts/sync_revisions.py 를 실행하거나 LAW_OC 등록을 확인하세요.")

    by_law: dict[str, list] = {}
    synced = None
    for r in rows:
        by_law.setdefault(r["law_id"], []).append(r)
        if r["synced_at"]:
            synced = max(synced or "", r["synced_at"])

    laws = []
    for rs in by_law.values():
        cur = next((x for x in rs if x["status"] == "현행"), None)
        upcoming = sorted((x for x in rs if x["status"] == "시행예정"),
                          key=lambda x: x["effective_on"])
        history = [x for x in rs if x["status"] == "연혁"]
        laws.append(LawStatus(
            law_id=rs[0]["law_id"], name=rs[0]["name"], ministry=rs[0]["ministry"] or "",
            current=_row_to_rev(cur) if cur else None,
            upcoming=[_row_to_rev(x) for x in upcoming],
            history_count=len(history),
            latest_effective_on=_ymd(cur["effective_on"]) if cur else None,
        ))
    order = {n: i for i, n in enumerate(TRACKED_LAWS)}
    laws.sort(key=lambda L: order.get(L.name, 99))
    return LawRevisionsResponse(laws=laws, tracked=len(TRACKED_LAWS), synced_at=synced)


@router.get("/{law_id}/revisions", response_model=LawTimelineResponse,
            dependencies=[Depends(require_api_key)])
def timeline(law_id: str):
    """한 법령의 전체 개정 이력(시행일 내림차순)."""
    conn = db()
    lawapi.ensure_tables(conn)
    _bootstrap_if_empty(conn)
    rows = conn.execute(
        "SELECT * FROM law_revisions WHERE law_id=? ORDER BY effective_on DESC", (law_id,)
    ).fetchall()
    if not rows:
        raise HTTPException(404, f"law_id={law_id} 의 개정 이력이 없습니다(동기화 필요).")
    return LawTimelineResponse(
        law_id=law_id, name=rows[0]["name"], revisions=[_row_to_rev(r) for r in rows])


@router.get("/diff", response_model=LawDiffResponse, dependencies=[Depends(require_api_key)])
def diff(
    law_id: str = Query(..., description="법령ID(법령일련번호 아님)"),
    from_effective: str = Query(..., alias="from", description="이전(개정 전) 버전 시행일 YYYYMMDD"),
    to_effective: str = Query(..., alias="to", description="이후(개정 후) 버전 시행일 YYYYMMDD"),
):
    """두 시행일 버전의 조문을 비교 → 추가/삭제/변경 조문 before/after."""
    conn = db()
    lawapi.ensure_tables(conn)
    _bootstrap_if_empty(conn)

    def resolve(ef):
        efd = re.sub(r"\D", "", ef)
        r = conn.execute(
            "SELECT mst,name FROM law_revisions WHERE law_id=? AND effective_on=?",
            (law_id, efd)).fetchone()
        return (r["mst"], r["name"], efd) if r else (None, None, efd)

    fm, name1, fef = resolve(from_effective)
    tm, name2, tef = resolve(to_effective)
    if not fm or not tm:
        raise HTTPException(
            404, "해당 시행일 버전을 찾지 못했습니다. /v1/laws/{law_id}/revisions 의 effective_on 을 사용하세요.")

    try:
        before = lawapi.version_articles(conn, law_id, fm, fef)
        after = lawapi.version_articles(conn, law_id, tm, tef)
    except lawapi.LawApiError as e:
        raise HTTPException(502, f"법제처 조문 조회 실패: {e}") from e

    diffs: list[ArticleDiff] = []
    added = removed = changed = 0
    for k in sorted(set(before) | set(after), key=_art_sort_key):
        a, b = before.get(k), after.get(k)
        if a and not b:
            removed += 1
            diffs.append(ArticleDiff(article_no=k, article_title=a[0], change="removed", before=a[1]))
        elif b and not a:
            added += 1
            diffs.append(ArticleDiff(article_no=k, article_title=b[0], change="added", after=b[1]))
        elif a and b and a[1] != b[1]:
            changed += 1
            diffs.append(ArticleDiff(article_no=k, article_title=b[0] or a[0],
                                     change="changed", before=a[1], after=b[1]))
    return LawDiffResponse(
        law_id=law_id, name=name2 or name1, from_effective_on=_ymd(fef), to_effective_on=_ymd(tef),
        added=added, removed=removed, changed=changed, diffs=diffs)

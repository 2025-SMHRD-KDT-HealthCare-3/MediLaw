"""영어 입력 지원 — 공식 영문 법령(articles_en) 조회 + 언어 감지.

- **법령**: scripts/ingest_elaw.py 로 법제처 elaw API에서 적재한 **공식 영문** 사용.
- **판례·해석례·가이드라인**: 공식 영문이 없어 답변 생성 단계에서 LLM이 비공식 번역.
영어 질의는 검색 직전 한국어로 번역(FTS가 한글 토큰이라 필수). llm.translate 사용.
"""
import re
import sqlite3

from app.db import db

_HANGUL = re.compile(r"[가-힣]")


def detect_lang(text: str) -> str:
    """한글 비율로 'ko'|'en' 추정(간이). 글자가 없으면 ko."""
    if not text:
        return "ko"
    hangul = len(_HANGUL.findall(text))
    letters = sum(1 for c in text if c.isalpha())
    if letters == 0:
        return "ko"
    return "ko" if hangul / letters >= 0.15 else "en"


def english_article(source_id: int):
    """statute hit(article id) → 공식 영문 행 또는 None.

    {law_name_en, article_no, title_en, body_en, eng_effective}
    """
    try:
        ko = db().execute(
            """SELECT s.name AS law_ko, a.article_no
               FROM articles a JOIN statutes s ON s.id = a.statute_id
               WHERE a.id = ?""",
            (source_id,),
        ).fetchone()
        if not ko:
            return None
        return db().execute(
            """SELECT law_name_en, article_no, title_en, body_en, eng_effective
               FROM articles_en WHERE law_name_ko = ? AND article_no = ? LIMIT 1""",
            (ko["law_ko"], ko["article_no"]),
        ).fetchone()
    except sqlite3.OperationalError:
        # articles_en 미적재(공식 영문 미설치 — ingest_elaw 미실행) 등 → 공식 영문 없이 진행.
        # 호출부(chat.py lang=en)는 한국어 소스(label/snippet) 기반으로 영어 답변에 비공식 번역.
        return None

"""챗봇 도메인 라우터 — 3-tier 사전 분류(결정론적 규칙 → 제약 LLM → 되묻기).

MediLaw 적용 (의료법만이 아니라 4대 법령 전체 + 의료·헬스케어 범위):
  Tier 1 = 일반 개인정보/정보통신망(의료·환자·건강정보 맥락 없음)            → 답변
  Tier 2 = 의료·헬스케어(의료법·생명윤리법·의료광고·진료·환자·건강정보),
           또는 표면은 일반이나 의료기관·환자·건강정보로 번질 여지가 있음     → 답변(서비스 핵심)
  Tier 3 = 위 어디에도 해당 안 됨(부동산·노동·세무·날씨·코딩·일반상식 등)     → 거절

⚠️ 레퍼런스(순수 개인정보·정보보호 챗봇)와 달리 '순수 의료 질문'은 Tier 3(범위 밖)이
   아니라 Tier 2(핵심)다 — MediLaw 챗봇은 의료법 질의응답이 본 기능이기 때문.

흐름: 1) 결정론적 규칙(확신 시 tier 확정, LLM 호출 0) → 2) 모호한 중간만 제약 LLM
     1회 위임 → 3) 저신뢰면 needs_clarification(되묻기). 키워드 사전은 오분류 로그
     보며 계속 보강하는 부분.
"""
from app import llm

# 답변할 tier(거절은 Tier 3). 정책: 일반 개인정보(Tier 1)도 답변.
# 만약 '헬스케어 맥락만' 답변하려면 IN_SCOPE_TIERS = (2,) 로 바꾸면 됨.
IN_SCOPE_TIERS = (1, 2)


# ── 1. 키워드 사전 (운영하며 오분류 로그 보고 보강) ────────────────────────────
MEDICAL_TRIGGERS = [
    "환자", "진료", "병원", "의원", "의료기관", "진료기록", "의무기록", "처방", "투약",
    "처방전", "건강검진", "검진", "검사결과", "건강정보", "진료정보", "임상", "임상시험",
    "비급여", "의료기기", "보건의료데이터", "진단", "의료영상", "내원", "의료법", "의료인",
    "무면허", "의료광고", "면허", "비대면진료", "원격의료", "생명윤리", "인간대상연구",
    "배아", "줄기세포", "유전자검사", "irb", "수술", "시술", "수진자", "의약품", "제약",
]

PRIVACY_NET_ANCHORS = [
    "개인정보", "정보보호", "정보통신망", "cctv", "영상정보", "수집", "보관", "파기",
    "동의", "제3자", "제공", "위탁", "스팸", "광고성", "마케팅", "수신동의", "유출",
    "가명정보", "가명처리", "민감정보", "처리방침", "열람", "정정", "삭제", "개인정보처리",
    "개인정보보호법", "정보통신망법",
]

# 프라이버시 사안이지만 헬스케어로 자주 번지는 키워드 → 규칙으로 단정하지 않고 LLM 위임.
AMBIGUITY_FLAGS = [
    "cctv", "영상정보", "마케팅", "광고", "문자", "직원", "임직원", "고객정보",
    "회원정보", "검진", "동의서",
]


def _contains(text: str, vocab: list[str]) -> bool:
    t = (text or "").lower()
    return any(kw.lower() in t for kw in vocab)


# ── 2. 1차: 결정론적 규칙 (확신 시 tier, 아니면 None → LLM) ─────────────────────
def rule_based_route(question: str, has_history: bool = False):
    """확신 가능한 경우만 tier(1|2|3) 반환, 모호하면 None(→ LLM 위임).

    has_history=True 이면 키워드 없는 짧은 후속질문("그럼 처벌은?")을 하드 거절하지 않고
    LLM(맥락 보유)에 위임한다 — 멀티턴 후속이 거절되는 것을 방지.
    """
    has_med = _contains(question, MEDICAL_TRIGGERS)
    has_priv = _contains(question, PRIVACY_NET_ANCHORS)
    is_ambiguous = _contains(question, AMBIGUITY_FLAGS)

    if has_med:                                   # 의료/헬스케어 명시 → 핵심(Tier 2)
        return 2
    if has_priv and not is_ambiguous:             # 순수 일반 개인정보/정보통신(번질 여지 없음)
        return 1
    if not has_priv and not has_med:              # 키워드 없음
        return None if has_history else 3         # 대화 중이면 후속일 수 있어 LLM에 위임
    return None                                   # priv + 모호 플래그 → LLM 위임


# ── 3. 2차: 제약된 LLM 분류기 (JSON 한 줄) ────────────────────────────────────
CLASSIFIER_SYSTEM = (
    "너는 한국 의료·헬스케어 컴플라이언스 챗봇(MediLaw)의 질문 분류기다. "
    "사용자 질문을 아래 3개 Tier 중 하나로만 분류하고 JSON으로만 답한다.\n"
    "Tier 1 = 개인정보보호법/정보통신망법 일반 질문(의료·환자·건강정보 맥락 없음).\n"
    "Tier 2 = 의료·헬스케어 관련(의료법·생명윤리법·의료광고·진료·환자·건강정보), 또는 "
    "표면은 일반이나 의료기관·환자·건강정보로 번지거나 그럴 여지가 있음.\n"
    "Tier 3 = 위 어디에도 해당하지 않음(부동산·노동·세무·날씨·코딩·일반상식 등).\n"
    "맥락이 불확실해 의료기관 상황인지 단정할 수 없으면 needs_clarification 을 true 로.\n"
    "짧은 후속 질문이면 직전 대화로 의도를 판단한다.\n"
    '반드시 JSON만 출력: {"tier": 2, "needs_clarification": false}\n'
    '예: "쇼핑몰 회원 정보 보관기간?" -> {"tier":1,"needs_clarification":false}\n'
    '예: "직원 건강검진 결과를 인사팀이 보관해도 되나요?" -> {"tier":2,"needs_clarification":false}\n'
    '예: "사무실 CCTV 안내문 꼭 붙여야 하나요?" -> {"tier":2,"needs_clarification":true}\n'
    '예: "무면허로 시술하면 처벌받나요?" -> {"tier":2,"needs_clarification":false}\n'
    '예: "야근수당 계산법 알려줘" -> {"tier":3,"needs_clarification":false}'
)


def llm_classify(question: str, history: list[dict] | None = None) -> tuple[int, bool]:
    """모호한 질문만 제약 LLM으로 분류. 실패 시 (2, True) — 핵심으로 보고 되묻기(안전)."""
    user = ""
    if history:
        convo = "\n".join(f"{t['role']}: {t['content']}" for t in history[-4:])
        user = f"[이전 대화]\n{convo}\n\n"
    user += f'질문: "{question}"'
    try:
        data = llm.chat_json([
            {"role": "system", "content": CLASSIFIER_SYSTEM},
            {"role": "user", "content": user},
        ])
        tier = int(data.get("tier"))
        if tier not in (1, 2, 3):
            raise ValueError("tier out of range")
        return tier, bool(data.get("needs_clarification", False))
    except Exception:  # noqa: BLE001
        return 2, True


# ── 4. 오케스트레이터 ─────────────────────────────────────────────────────────
def route(question: str, history: list[dict] | None = None) -> dict:
    """{tier, needs_clarification, source('rule'|'llm')}. 규칙으로 끝나면 LLM 호출 0."""
    t = rule_based_route(question, has_history=bool(history))
    if t is not None:
        return {"tier": t, "needs_clarification": False, "source": "rule"}
    tier, needs = llm_classify(question, history)
    return {"tier": tier, "needs_clarification": needs, "source": "llm"}


def is_in_scope(decision: dict) -> bool:
    return decision.get("tier") in IN_SCOPE_TIERS

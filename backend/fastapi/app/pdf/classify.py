"""PDF 문서종류 자동 분류 — doc_type 4종 자동 판별.

호출자가 doc_type을 주지 않으면(None) 추출된 블록 텍스트로 자동 분류한다.
domain_router.py 패턴 재사용: **결정론적 키워드 규칙 1차(LLM 0) → 모호하면 제약 LLM 2차**.
규칙 1차는 키 없이도 동작하고, LLM 2차는 graceful(실패 시 규칙 최선값/기본값).

4종: "ad"(광고/홍보) · "consent"(동의서) · "privacy_policy"(개인정보 처리방침) · "terms"(약관/이용약관).
"""
from app import llm
from app.pdf.schema import Block, DocType

# 분류 불가/폴백 시 기본값 (계약·약관류가 가장 흔하고 무난).
DEFAULT_DOCTYPE: str = "terms"

# 자동 분류 시 앞에서 모으는 텍스트 길이 상한(앞쪽 제목/머리말로 충분, 비용·노이즈 통제).
_HEAD_CHARS = 2000


# ── 1. 키워드 사전 (실제 문서 보며 보강하는 부분) ─────────────────────────────
# privacy_policy 와 consent 는 둘 다 "개인정보"가 등장하므로, 변별 신호를 먼저 둔다.
DOCTYPE_KEYWORDS: dict[str, list[str]] = {
    "privacy_policy": [
        "개인정보 처리방침", "개인정보처리방침", "처리방침", "개인정보 보호책임자",
        "개인정보보호책임자", "처리하는 개인정보의 항목",
        # 영어 신호(영어 문서 분류용) — 한국어 문서엔 안 나타나므로 한국어 분류엔 영향 없음.
        "privacy policy", "data protection officer", "retention period",
        "personal data we collect", "how we use your data",
    ],
    "consent": [
        "수집·이용 동의", "수집ㆍ이용 동의", "수집 및 이용 동의", "제3자 제공 동의",
        "민감정보 동의", "민감정보 처리 동의", "고유식별정보", "동의서", "동의합니다",
        "동의하지 않을 권리", "위 내용에 동의",
        # 영어 신호 — 동의 양식.
        "consent form", "i consent", "i agree", "collection and use",
        "sensitive information consent", "right to refuse consent",
    ],
    "terms": [
        "이용약관", "약관", "제1조", "제 1 조", "회원", "이용계약", "서비스 이용",
        "회원가입", "계약의 성립",
        # 영어 신호 — 약관/계약.
        "terms of service", "terms and conditions", "terms of use", "user agreement",
        "article 1", "membership",
    ],
    "ad": [
        "이벤트", "할인", "최초", "특가", "프로모션", "무료", "체험", "쿠폰",
        "사은품", "선착순", "혜택", "런칭", "오픈기념", "한정",
        # 치료경험담·과장 광고 신호 (후기형 의료광고가 'ad'로 분류되도록)
        "후기", "경험담", "완치", "보장",
        # 영어 신호 — 마케팅/과장 광고.
        "event", "discount", "sale", "promotion", "coupon", "limited-time",
        "limited time", "free trial", "testimonial", "review", "guarantee",
        "best", "only", "no.1", "#1",
    ],
}

# 동점/모호 판정 시 우선순위(앞쪽이 더 구체적인 신호) — privacy_policy·consent를 광고/약관보다 우선.
_PRIORITY: list[str] = ["privacy_policy", "consent", "terms", "ad"]


def _score(text: str) -> dict[str, int]:
    """doc_type별 키워드 매칭 횟수."""
    t = (text or "").lower()
    return {
        dt: sum(t.count(kw.lower()) for kw in kws)
        for dt, kws in DOCTYPE_KEYWORDS.items()
    }


# ── 2. 1차: 결정론적 규칙 (확신 시 doc_type, 아니면 None → LLM) ────────────────
def rule_based_classify(text: str) -> str | None:
    """확신 가능하면 doc_type, 모호하면 None(→ LLM 위임).

    확신 기준: 최고 득점이 0보다 크고, 유일한 최고이거나 우선순위로 또렷이 갈릴 때.
    """
    scores = _score(text)
    best = max(scores.values()) if scores else 0
    if best == 0:
        return None  # 키워드 전무 → LLM 위임
    winners = [dt for dt, s in scores.items() if s == best]
    if len(winners) == 1:
        return winners[0]
    # 동점: 우선순위로 가르되, 동점자가 우선순위상 명확히 1순위면 채택, 아니면 LLM 위임.
    for dt in _PRIORITY:
        if dt in winners:
            return dt
    return None


# ── 3. 2차: 제약된 LLM 분류기 (JSON 한 줄) ────────────────────────────────────
_CLASSIFIER_SYSTEM = (
    "너는 한국 법무/컴플라이언스 문서 분류기다. 주어진 문서 본문을 아래 4종 중 "
    "정확히 하나로만 분류하고 JSON으로만 답한다.\n"
    "ad = 광고/홍보물(이벤트·할인·프로모션·체험 등 마케팅 문구).\n"
    "consent = 동의서(개인정보 수집·이용/제3자 제공/민감정보 등에 대한 동의 양식).\n"
    "privacy_policy = 개인정보 처리방침(처리 항목·보유기간·보호책임자 등을 고지하는 문서).\n"
    "terms = 이용약관/약관(제1조·회원·서비스 이용계약 등 조항형 계약 문서).\n"
    "동의서(consent)와 처리방침(privacy_policy)은 둘 다 개인정보를 다루지만, "
    "동의를 받는 양식이면 consent, 처리 현황을 고지하는 문서면 privacy_policy 다.\n"
    '반드시 JSON만 출력: {"doc_type": "terms"}'
)


def llm_classify(text: str) -> str | None:
    """모호한 문서만 제약 LLM으로 분류. 실패/키없음 시 None(→ 호출부가 폴백)."""
    snippet = (text or "")[:_HEAD_CHARS]
    try:
        data = llm.chat_json([
            {"role": "system", "content": _CLASSIFIER_SYSTEM},
            {"role": "user", "content": f"문서 본문:\n{snippet}"},
        ])
        dt = str(data.get("doc_type", "")).strip()
        if dt in DOCTYPE_KEYWORDS:
            return dt
        return None
    except Exception:  # noqa: BLE001  — LLMUnavailable/네트워크/파싱 등 모두 graceful
        return None


# ── 4. 오케스트레이터 ─────────────────────────────────────────────────────────
def classify_doctype(text: str) -> str:
    """텍스트를 doc_type 4종 중 하나로 분류. 규칙으로 확신하면 LLM 호출 0.

    규칙 모호 시 LLM 위임 → LLM도 실패하면 규칙 최선값(있으면)/DEFAULT_DOCTYPE.
    항상 4종 중 하나(DocType)를 반환한다.
    """
    ruled = rule_based_classify(text)
    if ruled is not None:
        return ruled
    via_llm = llm_classify(text)
    if via_llm is not None:
        return via_llm
    # LLM도 실패: 점수가 있으면 우선순위로 최선값, 아니면 기본값.
    scores = _score(text)
    if scores and max(scores.values()) > 0:
        for dt in _PRIORITY:
            if scores[dt] == max(scores.values()):
                return dt
    return DEFAULT_DOCTYPE


def classify_blocks(blocks: list[Block]) -> str:
    """앞쪽 블록 텍스트를 모아 classify_doctype 호출 — 자동 분류 진입점."""
    head, total = [], 0
    for b in blocks:
        txt = (b.text or "").strip()
        if not txt:
            continue
        head.append(txt)
        total += len(txt)
        if total >= _HEAD_CHARS:
            break
    return classify_doctype("\n".join(head))


# ── 5. 자체 검증 (pytest + __main__ 러너) ─────────────────────────────────────
def test_rule_clear_cases_no_llm():
    """규칙으로 명확한 4종은 LLM 없이도 정확해야 한다(키 없어도 통과)."""
    assert rule_based_classify("개인정보 처리방침 제1조 목적") == "privacy_policy"
    assert rule_based_classify("수집·이용에 동의합니다 민감정보 동의") == "consent"
    assert rule_based_classify("이번 이벤트 국내 최초 무료 체험 특가") == "ad"
    assert rule_based_classify("이용약관 제1조 회원의 의무") == "terms"


def test_classify_returns_valid_doctype():
    """항상 4종 중 하나를 반환한다(빈 입력 폴백 포함)."""
    valid = set(DOCTYPE_KEYWORDS)
    for t in ["", "아무 의미 없는 텍스트", "개인정보 처리방침"]:
        assert classify_doctype(t) in valid


def test_empty_falls_back_to_default():
    assert classify_doctype("") == DEFAULT_DOCTYPE


def test_classify_blocks():
    blocks = [
        Block(id="b1", type="heading", text="이용약관", page=1, source="digital"),
        Block(id="b2", type="para", text="제1조 회원의 의무", page=1, source="digital"),
    ]
    assert classify_blocks(blocks) == "terms"


if __name__ == "__main__":
    cases = [
        ("개인정보 처리방침 제1조 목적", "privacy_policy"),
        ("수집·이용에 동의합니다 민감정보 동의", "consent"),
        ("이번 이벤트 국내 최초 무료 체험 특가", "ad"),
        ("이용약관 제1조 회원의 의무", "terms"),
        # 영어 문서 분류 — 영어 신호로 올바르게 갈리는지.
        ("Limited-time 50% discount event! Real patient review.", "ad"),
        ("Privacy Policy. Retention period and data protection officer.", "privacy_policy"),
        ("Terms of Service. Article 1. Membership.", "terms"),
        ("Consent Form. I agree to the collection and use of my data.", "consent"),
    ]
    for t, exp in cases:
        got = classify_doctype(t)
        mark = "OK" if got == exp else "??"
        print(f"  [{mark}] {got:15} expect~{exp:15} :: {t[:24]}")
    print("  empty ->", classify_doctype(""))

# MediLaw API (FastAPI)

의료·헬스케어 사업자를 위한 **의료법 컴플라이언스 AI 백엔드**. [lawbot.org](https://lawbot.org/) 4대 기능(RAG·Source Pack·Citation Firewall·MCP)을 엔진으로, **기획서 6대 핵심 기능**을 의료 4법령 도메인에 구현했다.
대상 법령: **의료법 · 개인정보 보호법 · 생명윤리법 · 정보통신망법** + 보건의료 행정규칙·판례·해석례·가이드라인.
스택: FastAPI + SQLite(FTS5 + sqlite-vec) + OpenAI(gpt-5.5 생성, text-embedding-3-small 임베딩) + 법제처 Open API.

> ⚠️ 작업 제1원칙: 이 디렉토리(`backend/fastapi`) 안에서만 작업 (`CLAUDE.md` 참고).
> 백엔드는 2개로 분리(기획서): **Node.js**(회원·세션·대화이력·MySQL·라우팅) + **이 FastAPI**(AI·RAG·검증·법령). 프론트(React)·시각화 UI·Node는 이 디렉토리 밖.

## 기획서 6대 핵심 기능 → 구현 매핑 (한눈에)

| # | 기획서 핵심 기능 | 구현 엔드포인트 | 상태 |
|---|---|---|---|
| ① | AI 질의응답 챗봇(RAG) | `POST /chat/stream`(SSE) · `POST /chat` | ✅ |
| ② | PDF 문서 분석(능동형 에디터) | `POST /documents/review` (before/after + 비전 OCR) | ✅ |
| ③ | Citation Verification(환각 방지) | `POST /v1/verify` (+ ①②④에 자동 내장) | ✅ |
| ④ | 능동형 체크리스트 | `POST /chat/checklist`(대화 기반) · `/documents/review`(문서 기반) | ✅ |
| ⑤ | 법령 개정 현황 대시보드 | `GET /v1/laws/revisions · /{law_id}/revisions · /diff` (법제처 API) | ✅ |
| ⑥ | 해외기업용 영어 입력 | `lang=en` (①②④ 공통 — 법령은 공식 영문) | ✅ |

> **6대 기능 백엔드 전부 구현·라이브 검증 완료.** 남은 건 프론트엔드(React) UI뿐. 기능별 상세는 [API 엔드포인트 상세](#-api-엔드포인트-상세).

## 구현 현황 (세부)

- [x] **RAG API / Source Pack / Citation Firewall / MCP**(4도구) — lawbot 4대 기능
- [x] **하이브리드 검색** FTS5 + OpenAI 임베딩(text-embedding-3-small, 512d) RRF, **sub-chunk**(대형 문서 분할)
- [x] **데이터**: 4대 법령+시행령/규칙, 행정규칙, 판례, **법령해석례·개인정보위 결정문·보건복지부 가이드라인**(의료광고 등) — 법제처 Open API + 게시판 수집기
- [x] **임베딩 빌드 완료** chunks 212,459 (sqlite-vec)
- [x] **AI 챗봇** `POST /chat`(+SSE) — gpt-5.5 RAG + Citation Firewall 검증 + **3-tier 도메인 라우터**(규칙→제약LLM→되묻기, 4대 법령 전체·헬스케어 범위)
- [x] **능동형 PDF 에디터** `POST /documents/review` — 위험 탐지 + before/after 수정안, 스캔본 **비전 OCR** fallback. **근거 연결·인덱스는 코드가**(코어 검색 기반), LLM은 판단·문구만
- [x] **영어 입력 지원** `lang=en` — 법령은 **공식 영문**(법제처 elaw API), 판례·해석례·가이드라인은 비공식 번역
- [x] **챗봇 멀티턴 기억** — `/chat`·`/chat/stream`이 `history[]`(이전 대화) 수신(무상태, 클라이언트 보관)
- [x] **능동형 체크리스트** — `/documents/review`가 "확인 필요 항목" 생성 + `prev_checklist` 대조로 추가/삭제/유지
- [x] **통합 체크리스트** `POST /chat/checklist` — '체크리스트 생성' 버튼: **대화(history) + PDF 검토(reviews)** 종합 → 법적 쟁점 추출 → RAG 근거검색 → 통합 대응 체크리스트
- [x] **법령 개정 현황 대시보드** `GET /v1/laws/*` — 법제처 데이터로 4대 법령 개정 타임라인(현행·시행예정·연혁) + **개정 전후 조문 비교**(before/after) + 1일 1회 배치 동기화
- [x] **Node 연동 준비** — Node(메인)→FastAPI 서버-서버 호출 구조(CORS 불필요) + `fetch` SSE·multipart [호출 예제](#node-호출-예제)
- [ ] 프론트엔드(React 챗 UI·대시보드 UI) — 미구현(이 백엔드 API를 호출만 하면 됨)

## API 한눈에 보기

> 베이스 URL 예: `http://localhost:8077` · 문서(Swagger): `GET /docs`
> 인증: `API_KEYS` 설정 시 `x-api-key` 헤더 필수(미설정이면 생략). 분당 레이트리밋 적용.

| 분류 | 메서드 · 경로 | 용도 |
|---|---|---|
| 🟢 **프론트용** | `POST /chat/stream` | AI 질의응답 챗봇(SSE 스트리밍) |
| 🟢 **프론트용** | `POST /documents/review` | PDF/텍스트 위험 검토 + before/after(전체 한 번에) |
| 🟢 **프론트용** | `POST /documents/review/stream` | 위와 동일, **페이지별 SSE 점진 노출**(앞 페이지부터) |
| 🟢 **프론트용** | `POST /chat/checklist` | '체크리스트 생성' 버튼 — 대화+PDF검토 종합 → 통합 체크리스트 |
| 🟢 **프론트용** | `POST /v1/related-graph` | 인용 `[n]`/finding **더보기** 클릭 → 연관 판례 엣지-노드 그래프 JSON |
| 챗봇(단발) | `POST /chat` | 위와 동일, JSON 한 번에 반환(느림) |
| 코어 | `POST /v1/retrieve` | 하이브리드 RAG 검색 |
| 코어 | `POST /v1/source-pack` | LLM 인용용 근거 마크다운 번들 |
| 코어 | `POST /v1/verify` | Citation Firewall(인용 검증) |
| 코어 | `GET /v1/statutes/search` | 법령 검색(lawbot 호환) |
| 대시보드 | `GET /v1/laws/revisions` | 4대 법령 개정 현황(현행·시행예정·연혁) |
| 대시보드 | `GET /v1/laws/{law_id}/revisions` | 한 법령 개정 이력 타임라인 |
| 대시보드 | `GET /v1/laws/diff` | 개정 전후 조문 비교표(before/after) |
| 에이전트 | `/mcp/sse` | MCP 서버(4도구) — uvicorn에 마운트 |
| 운영 | `GET /health`, `GET /` | 상태 점검 / 기능 인덱스(인증 없음) |

> **프론트(React)는 🟢 표시 + 대시보드 `/v1/laws/*`만 호출**하면 됩니다. 코어 `/v1/{retrieve,source-pack,verify,statutes}`는 🟢 엔드포인트가 내부에서 호출하는 공유 엔진이자 MCP/외부 에이전트용 표면입니다(프론트가 직접 부를 필요 없음). → [엔드유저 vs 코어](#엔드유저2개-vs-코어-구분)

---

## 기능 검증 (smoke test)

로컬(`DB_PATH=data/medilaw.db`, 인증 off, `OPENAI_API_KEY` 설정) 기준 각 기능 빠른 확인:

| # | 기능 | 검증 방법 | 기대 |
|---|---|---|---|
| 1 | RAG 검색 | `POST /v1/retrieve {"query":"무면허 의료행위"}` | `output` 비어있지 않음, `method:"hybrid"` |
| 2 | Source Pack | `POST /v1/source-pack {"query":"의료광고 심의"}` | `output` 마크다운 + `citations[]` |
| 3 | Citation Firewall | `POST /v1/verify {"text":"의료법 제27조와 가짜 의료법 제999조"}` | 제27조 `확인`(trust_score≥85) / 제999조 `오류`(25), `avg_score` |
| 4 | 법령 검색 | `GET /v1/statutes/search?q=의료광고` | `output[]` |
| 5 | AI 챗봇 | `POST /chat {"question":"..."}` | `answer`+`sources`+`citation_check` |
| 6 | 멀티턴/재작성 | `history` 포함 호출 | `search_query`가 standalone으로 재작성 |
| 7 | PDF 에디터 | `POST /documents/review -F text=...` | `findings`+`checklist`+`revised_text` |
| 8 | 능동형 체크리스트 | `prev_checklist` 재전달 | `change`(added/kept/removed)·`checklist_summary` 갱신 |
| 9 | 영어 입력 | `POST /chat {"question":"...","lang":"en"}` | 영어 답변, 법령은 `is_official_en:true` |
| 10 | MCP 서버 | `GET /health` | `mcp_mounted:true` (도구 4) |
| 11 | 대화 종료 체크리스트 | `POST /chat/checklist {"history":[...]}` | `checklist[]`(근거 인용) + `search_queries` |
| 12 | 개정 대시보드 | `GET /v1/laws/revisions` | 4대 법령 현행·시행예정·연혁 |
| 13 | 개정 전후 비교 | `GET /v1/laws/diff?law_id=001788&from=20200328&to=20260407` | `changed`>0, 조문 before/after |

> ✅ **검증 완료** — 전 기능 로컬 라이브 호출로 PASS.
> ①~⑥ 기획서 기능 + 코어/MCP: RAG(method=hybrid) · Citation Firewall(제27조 verified/제999조 failed) · 챗봇(인용+후속질문 standalone 재작성) · PDF 에디터(before/after+체크리스트) · 영어 입력(공식 영문 부착) · **대화 체크리스트**(근거 기반 8항목) · **개정 대시보드**(법제처 4법령 197버전, 의료법 2020→2026 41조문 diff) · MCP(도구 4).
> 성능 실측은 [성능](#성능-실측) 참고(`REASONING_EFFORT=low` 적용 — 챗봇 완답 ~4.3s).

## 📖 API 엔드포인트 상세

### 1. `POST /chat/stream` — AI 챗봇 (SSE) 🟢

질문 → **도메인 라우터(3-tier)** → 하이브리드 근거검색 → **gpt-5.5** 답변(근거 `[n]` 강제 인용) → **Citation Firewall** 자동검증.
> **도메인 라우터**(`app/domain_router.py`): 결정론적 키워드 규칙으로 대부분 분류(LLM 호출 0), 모호한 중간만 제약 LLM 1회. 회귀 테스트는 `tests/test_domain_router.py`.
> - **Tier 1** 일반 개인정보/정보통신망(의료 맥락 없음) → 답변 · **Tier 2** 의료·헬스케어(의료법·생명윤리·의료광고·환자·건강정보, 또는 프라이버시가 헬스케어로 번짐) → 답변(핵심) · **Tier 3** 무관(부동산·노동·날씨·코딩) → 거절(`sources:[]`·`method:"none"`).
> - Tier 2 모호(예 "사무실 CCTV")는 답변 끝에 **되묻기 한 줄**(needs_clarification) 부착. 멀티턴 후속질문은 맥락으로 판정.
단발 JSON이 필요하면 동일 body로 `POST /chat`(아래 응답 본문과 같은 형태, 완답까지 기다림 → UI는 첫 글자가 ~2초에 뜨는 스트리밍 권장. [성능](#성능-실측) 참고).

**요청** `Content-Type: application/json`
```json
{
  "question": "병원 광고에 '국내 최초'라고 써도 되나요?",
  "history": [                 // 멀티턴(선택) — 클라이언트가 보관·전달, 최근 10턴만 사용
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "top_k": 8,                  // 1~20, 검색 근거 수
  "source_types": null,        // ["statute","case","interpretation","decision","guideline"] 필터(선택)
  "as_of": null,               // "2024-01-01" 시점 조회(선택)
  "lang": "auto"               // auto|ko|en — en이면 영어로 답변(아래 "영어 입력 지원")
}
```
> **멀티턴**: FastAPI는 무상태입니다. 대화이력은 클라이언트(→Node/MySQL)가 보관하고 매 요청에 `history`로 되돌려줍니다. `history`가 있으면 후속질문("그럼 그건?")을 **독립 검색질의로 재작성**해 RAG 정확도를 높입니다(응답 `search_query`에 실제 사용 질의 노출).

**응답** `text/event-stream` — `data:` 한 줄이 한 이벤트. 3종이 순서대로:
```
data: {"type":"sources","method":"hybrid","sources":[
  {"n":1,"label":"대법원 2006도9311","source_type":"case","source_id":123,
   "snippet":"...","source_url":"https://...","trust_grade":"A"}]}

data: {"type":"token","text":"‘국내 최초’ 표현은 "}     ← N개 누적
data: {"type":"token","text":"의료법상 ... [1]"}

data: {"type":"done","citation_check":{
  "output":[{"raw":"의료법 제56조","type":"statute","exists":true,
             "clause_accurate":true,"valid_as_of":null,"verified":true,
             "trust_score":95,"status":"확인",
             "matched_label":"의료법 제56조","matched_source_url":"...","note":""}],
  "summary":{"total":1,"verified":1,"failed":0,"avg_score":95,"worst_status":"확인","min_score":95},"as_of":null}}
```
에러 시 `{"type":"error","message":"..."}`. ⚠️ 브라우저 `EventSource`는 GET만 지원 → POST는 `fetch` + `ReadableStream`으로 직접 파싱.

> **`answer_segments`** — `done` 이벤트(및 `/chat` 응답)에 답변을 `[n]` 기준으로 쪼갠 렌더용 배열이 함께 옵니다. `{type:"text"|"cite", text, n, source_type, source_id, label}` 토큰 배열이라 프론트가 정규식 파싱 없이 `cite` 토큰만 **클릭 가능**하게 그리면 됩니다. 클릭 시 그 토큰의 `{source_type, source_id}`를 그대로 [`/v1/related-graph`](#5-b-post-v1related-graph--연관-판례-그래프-) seed로 넘깁니다. (sources에 없는 `[n]`은 `text`로 강등 → 클릭 불가). → [프론트 연동 가이드](docs/frontend-related-graph.md)

```bash
curl -N -X POST localhost:8077/chat/stream -H 'content-type: application/json' \
  -d '{"question":"병원 광고에 \"국내 최초\" 표현 써도 되나요?","top_k":5}'
```

---

### 2. `POST /documents/review` — 능동형 PDF 에디터 🟢

문서(PDF/텍스트) → **신 PDF 파이프라인**(페이지 라우팅 → pdfplumber 텍스트·**표** ∥ 스캔본 **OCR** → doc_type 자동분류 → 세그먼트 → 위험판정 → 블록단위 before/after) → Citation Firewall.
결과로 **before/after**(원문 ↔ 수정본)와 위험 세그먼트별 사유·대안·근거를 돌려줍니다(응답: `ReviewResponse`).
> **LLM에 전부 위임하지 않음**: 근거 확보·인덱스·인용 연결 등 수치/구조는 **코드(코어 검색)**가, LLM은 위반여부·사유·대안 문구·risk_level만. OCR 기본 백엔드는 PaddleOCR-VL(자체호스팅)이며 **실패(가중치 차단·메모리 부족 등) 시 페이지 단위로 gpt-5.5 비전으로 자동 폴백**(`OCR_FALLBACK_BACKEND=vision`, 끄려면 빈 값). (체크리스트는 분리됨 → [`/chat/checklist`](#2-b-post-chatchecklist--통합-체크리스트대화--pdf-)).
> **OCR 실패 신호**: 스캔 페이지인데 텍스트 추출이 0이면 "위험 없음"과 헷갈리지 않도록 — 단발 `/documents/review`는 응답에 `ocr_failed_pages:[페이지번호…]`, 스트림은 해당 `page` 이벤트에 `"warning":"ocr_failed"`를 실어 보냅니다.

**🟢 페이지별 스트리밍** `POST /documents/review/stream` (SSE) — 큰 PDF에서 **앞 페이지부터 즉시** 보여주고 뒤는 처리되는 대로 채우는 UX용:
```
data: {"type":"pages","page_count":5,"routes":[{"page":1,"route":"digital"}, ...]}
data: {"type":"page","page":1,"progress":"1/5","doc_type":"ad",
       "original_text":"...","revised_text":"...",
       "segments":["세그먼트0 원문","세그먼트1 원문", ...],   ← findings.segment_index가 가리키는 페이지-로컬 배열
       "findings":[{"segment_index":0,
       "segment_text":"...","risk_level":"high","issue":"...","suggestion":"...","law":["..."]}]}
data: {"type":"page","page":3,"route":"scan","warning":"ocr_failed", ...}   ← 스캔 OCR 실패(텍스트 0)
data: {"type":"done","summary":{"page_count":5,"risky":3,"changes":2}}
```
> 프론트: `page` 이벤트를 받는 즉시 그 페이지 카드를 before/after로 렌더(순서대로). `findings[].segment_index`는 같은 이벤트의 `segments[]`를 가리키므로(페이지-로컬) `segments[finding.segment_index]`로 원문 역참조 가능. `pages=2,3` 폼 필드로 특정 페이지만도 가능.

**프론트 SSE 예제(JS)** — `multipart`로 PDF 업로드 + 페이지별 점진 수신:
```js
async function reviewStream(file, { onPages, onPage, onDone, onError } = {}) {
  const fd = new FormData();
  fd.append("file", file);              // <input type="file">의 File 객체
  // fd.append("pages", "1,2");         // (선택) 특정 페이지만
  const res = await fetch("http://localhost:8077/documents/review/stream", {
    method: "POST", body: fd /*, headers: { "x-api-key": KEY } */,
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n");     // SSE 이벤트 경계
    buf = events.pop();                   // 미완성 조각은 다음 청크로
    for (const ev of events) {
      const line = ev.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const msg = JSON.parse(line.slice(5).trim());
      if (msg.type === "pages") onPages?.(msg);        // 페이지 수만큼 스켈레톤 카드
      else if (msg.type === "page") onPage?.(msg);     // 그 페이지 카드 즉시 채움(before/after·findings)
      else if (msg.type === "done") onDone?.(msg.summary);
      else if (msg.type === "error") onError?.(msg);   // 한 페이지 실패(스트림은 계속)
    }
  }
}

// 사용 예
reviewStream(fileInput.files[0], {
  onPages: (m) => renderSkeletons(m.page_count),
  onPage:  (p) => fillCard(p.page, p.original_text, p.revised_text, p.findings),
  onDone:  (s) => showSummary(s),         // {page_count, risky, changes}
});
```
> ⚠️ 브라우저 `EventSource`는 GET·헤더 미지원 → 위처럼 `fetch`+`ReadableStream`으로 파싱(`/chat/stream`과 동일 패턴). React→Node→FastAPI 구조면 Node가 이 SSE를 받아 브라우저로 중계(passthrough).

**요청** `Content-Type: multipart/form-data` — `file`(PDF) **또는** `text` 중 하나 필수

| 필드 | 필수 | 설명 |
|---|---|---|
| `file` | ▲ | 검토할 PDF |
| `text` | ▲ | PDF 대신 본문 직접 입력 |
| `as_of` | – | 시점 조회 `YYYY-MM-DD` |
| `top_k_per_segment` | – | 세그먼트별 근거 수(기본 4, 1~8) |
| `lang` | – | `auto`\|`ko`\|`en` — 영문 문서 검토 시 `en`(아래 "영어 입력 지원") |
| `prev_checklist` | – | 직전 응답의 `checklist`를 JSON 배열로 전달 → 능동형 재조정(추가/삭제/유지) |

**응답** `application/json`
```json
{
  "original_text": "OO의원 국내 최초 무통증 시술\n부작용이 전혀 없는 100% 안전한 치료\n...",  // before
  "revised_text":  "OO의원 국내 최초 무통증 시술\n시술 전 효과·부작용 가능성을 충분히 안내합니다\n...", // after
  "segments": ["OO의원 국내 최초 무통증 시술", "부작용이 전혀 없는 100% 안전한 치료", "..."],
  "findings": [{
    "segment_index": 1,
    "segment_text": "부작용이 전혀 없는 100% 안전한 치료",   // before(세그먼트)
    "risk_level": "high",                                  // high | medium | low
    "issue": "절대적 안전성 단정은 의료광고 가이드라인 위반 소지...",
    "suggestion": "시술 전 효과·부작용 가능성을 충분히 안내합니다", // after(세그먼트)
    "citations": [{"n":1,"label":"[가이드라인] 의료광고 가이드라인.pdf",
                   "source_type":"guideline","source_id":45,"snippet":"...","source_url":"...","trust_grade":""}]
  }],
  "checklist": [{            // 능동형 확인목록 — 사람이 추가로 확인할 항목
    "id": "first-claim",     // 안정 식별자(재조정 시 유지)
    "title": "‘국내 최초’ 객관적 근거자료 보유 여부 확인",
    "reason": "근거 없는 최초/유일 표현은 과장광고 소지",
    "status": "todo",        // todo | ok | risk | na
    "change": "added",       // added | kept | updated | removed (prev_checklist 대비)
    "segment_index": 0,
    "citations": [{ "n":1, "label":"...", ... }],
    "note": ""               // 사용자 메모(prev_checklist로 보내면 보존됨)
  }],
  "checklist_summary": { "total":3, "todo":2, "ok":1, "risk":0, "na":0 },
  "extracted_by": "ocr",     // "text"=디지털 PDF / "ocr"=스캔본 비전 OCR
  "citation_check": {"output":[],"summary":{"total":0,"verified":0,"failed":0}},
  "method": "hybrid",
  "lang": "ko",
  "as_of": null
}
```
- **프론트 렌더**: `original_text`↔`revised_text` diff 뷰 / `findings[].segment_index`로 `segments[]`에서 위험 조각을 찾아 `risk_level`별 색칠 → 클릭 시 사유·대안·근거 패널 / `extracted_by==="ocr"`면 "OCR 인식(오인식 가능)" 배지.
- **능동형 체크리스트**: `checklist`를 할 일 목록으로 표시(`checklist_summary`로 진행률). 사용자가 문서를 고쳐 재요청할 때 직전 `checklist`를 `prev_checklist`로 보내면 해결 항목은 `change:"removed"`, 새 항목은 `"added"`로 동적 갱신. 사용자가 항목을 `ok`/`na`로 체크하거나 `note`를 달아 되돌려주면 다음 분석이 그 상태·메모를 **보존**합니다(단, 문서에 위반 문구가 명백히 남아 있으면 안전하게 `risk`로 재플래그).

```bash
curl -X POST localhost:8077/documents/review -F "file=@ad.pdf"
curl -X POST localhost:8077/documents/review -F "text=부작용 전혀 없는 100% 안전한 시술"
```

---

### 2-B. `POST /chat/checklist` — 통합 체크리스트(대화 + PDF) 🟢

'체크리스트 생성' 버튼용. 한 세션의 **챗봇 대화(`history`) + PDF 검토 결과(`reviews`)를 함께** 받아 → 법적 쟁점 추출(LLM) → 쟁점별 **RAG 근거검색** → **gpt-5.5**가 "법적으로 대응·준비하려면 추가로 확인할 항목"을 근거 기반으로 통합 생성. 무상태(클라이언트가 보관·전달).

> 종료 감지는 서버가 안 함 — 프론트의 버튼 클릭이 트리거. `history`·`reviews` **둘 중 하나 이상** 있으면 됨(둘 다 비면 400).

**요청** `Content-Type: application/json`
```json
{
  "history": [                 // 챗봇 대화(선택) — history·reviews 중 하나는 필수
    {"role": "user", "content": "환자 시술 전후 사진을 블로그 광고에 쓰려는데요"},
    {"role": "assistant", "content": "..."}
  ],
  "reviews": [                 // PDF 검토 결과(선택) — /documents/review 응답을 그대로 되돌려줌
    {"original_text": "부작용 전혀 없는 100% 안전한 시술",
     "findings": [{"segment_text": "...", "risk_level": "high", "issue": "과장광고 소지", "suggestion": "..."}]}
  ],
  "top_k": 6,                  // 쟁점별 근거 검색 수(1~20)
  "max_topics": 5,             // 추출할 법적 쟁점 수(1~8)
  "as_of": null,               // 시점 조회(선택)
  "lang": "auto",              // auto|ko|en
  "prev_checklist": null       // 직전 checklist 배열 재전달 시 사용자 status/note 보존(재생성)
}
```

**응답** `application/json`
```json
{
  "checklist": [{
    "id": "sensitive-consent",
    "title": "광고용 사진 이용에 대한 민감정보 동의서를 별도로 받아 보관할 것",
    "reason": "민감정보 동의에는 수집·이용 목적, 항목, 보유기간을 포함해야 함 [3]",
    "status": "todo",          // todo | ok | risk | na
    "change": "added",         // prev_checklist 대비 added|kept|updated|removed
    "segment_index": null,     // 대화 기반이라 항상 null
    "citations": [{"n":3,"label":"개인정보보호위원회 개인정보보호지침 제15조", ...}],
    "note": ""
  }],
  "checklist_summary": {"total":8,"todo":8,"ok":0,"risk":0,"na":0},
  "sources": [ ... ],          // RAG로 검색된 근거(번호 n)
  "search_queries": ["미용시술 전후사진 의료광고 환자 서면동의 요건", "..."],  // 추출된 쟁점(투명성)
  "citation_check": {"output":[],"summary":{"total":0,"verified":0,"failed":0}},
  "method": "hybrid", "lang": "ko", "as_of": null
}
```
- **프론트**: 챗 화면 '체크리스트 생성' 버튼 → 누적 `history` 전송 → `checklist`를 할 일 목록으로(진행률 `checklist_summary`). 사용자가 `ok`/`na` 체크·`note` 작성 후 다시 누르면 그 배열을 `prev_checklist`로 보내 상태 보존.
- ⚠️ 종합 리포트라 **한 번에 ~35초** 소요(2회 LLM + RAG). UI는 진행 표시 권장. [성능](#성능-실측) 참고.

```bash
curl -s -X POST localhost:8077/chat/checklist -H 'content-type: application/json' \
  -d '{"history":[{"role":"user","content":"환자 전후사진을 블로그 광고에 쓰려는데 국내 최초 무통증 문구도 넣을게요"}]}'
```

---

### 3. `POST /v1/retrieve` — RAG 하이브리드 검색 (코어)

질의 → FTS5 + 벡터 RRF 융합 → 조문·판례·해석례·결정문·가이드라인 통합 결과. `as_of` 시점 필터.

**요청** `{"query":"무면허 의료행위","top_k":8,"source_types":null,"as_of":null}`
**응답** `{"output":[Hit...],"as_of":null,"source":"medilaw.db","method":"hybrid"}`
`Hit = {source_type, source_id, label, title, snippet, score, trust_grade, effective_from, source_url}`

---

### 4. `POST /v1/source-pack` — 근거 마크다운 번들 (코어)

검색 결과를 **LLM이 그대로 인용**할 수 있는 번호 매긴 마크다운으로 패키징.

**요청** `{"query":"의료광고 사전심의","max_items":8,"source_types":null,"as_of":null}`
**응답** `{"output":"# 근거 자료 (Source Pack)\n## [1] ...","citations":[Citation...],"as_of":null}`

---

### 5. `POST /v1/verify` — Citation Firewall (코어)

AI 답변의 법령·판례 인용을 DB와 대조(존재·조문 정확성·판례 유효성·시점). `text`(자동 추출) 또는 `citations`(구조화) 중 하나 이상.

**요청** `{"text":"의료법 제27조와 가짜 의료법 제999조","as_of":"2026-06-15"}`
**응답** `{"output":[VerifyResult...],"summary":{...},"as_of":"2026-06-15"}`
- `VerifyResult = {raw, type(statute|case|unknown), exists, clause_accurate, valid_as_of, verified, trust_score, status, matched_label, matched_source_url, note}`
- `summary = {total, verified, failed, avg_score, worst_status, min_score}`

**신뢰 점수(`trust_score` 0~100) + 상태(`status`)** — 기획서대로 수치와 3단계를 함께 출력:

| status | trust_score | 의미 |
|---|---|---|
| `확인` | 85~100 | 존재·조문(+항)·시점 핵심검증 통과. 감점: 시점 미검증 −5 / 조문대조 불가 −10 / **B등급 출처(행정규칙) −5** |
| `주의` | 60~70 | 존재하나 `as_of` 시점엔 미발효(60)·구법 가능성(70) / 그 이후 선고 판례 / **법령명 매칭 모호(70)** |
| `오류` | 0~25 | 법령·판례 없음(0) / 조문·**항(項) 환각**(25, 법령은 있으나 그 조·항이 없음) |

검증 4축에 더해진 신호:
- **항(項) 단위 검증** — `제27조 제6항`처럼 존재하지 않는 항 인용도 환각(오류)으로 잡음(조문 본문의 ①~⑮ 대조).
- **출처 등급** — 법률(A)보다 행정규칙·고시(B) 매칭은 권위가 낮아 −5(상태는 불변).
- **모호 매칭** — 짧은 법령명이 긴 인용문에 헐겁게 매칭되면 `주의`(70)로 강등(정확 매칭은 영향 없음).
- **구법 인용 교차검증**(개정 대시보드 `law_revisions` 연계) — `as_of` 시점에 다른(구) 버전이 시행 중이었으면 `주의`로 낮추고 "현행과 비교 권장" note. 시행예정 개정이 있으면 정보성 note 부착.

`summary`: `avg_score`(평균) 외에 **`worst_status`/`min_score`** 제공 — 평균이 희석하는 "오류 1건이라도 있는지"를 바로 노출. 이 검증은 `/chat`·`/documents/review`의 `citation_check`에도 자동 내장.
> 예: `의료법 제27조`→`확인 95` · `제27조 제6항`(없는 항)→`오류 25` · 가짜 `제999조`→`오류 25` · `대법원 2006도9311`→`확인 85`.

---

### 5-B. `POST /v1/related-graph` — 연관 판례 그래프 🟢

챗봇 답변/PDF 검토에 인라인으로 뜬 인용 `[n]`(또는 finding)을 **더보기 클릭**했을 때 호출 → 보고 있던 문구를 **위반 쟁점별 판례·제재**의 엣지-노드 그래프로 구조화해 반환합니다(프론트가 마인드맵으로 렌더). 챗봇·PDF 공용.

> 흐름: `hybrid_search`로 실재 조문·판례 확보 → **gpt-5.5**가 쟁점 클러스터링 + 제재수위 추출(후보를 idx로만 참조) → **Citation Firewall**로 환각/오참조 idx 제거 → 그래프 JSON. LLM 불가/검색 0건이면 규칙 폴백(`llm:false`).

**요청** `Content-Type: application/json`
```json
{
  "text": "국내 1위·100% 효과",        // 보고 있던 문구/질의 (그래프 중심)
  "seeds": [                           // (선택) 클릭한 [n]이 가리키는 인용 — 그래프에 반드시 포함·강조
    {"source_type": "statute", "source_id": 10},
    {"source_type": "case", "source_id": 20}
  ],
  "lang": "ko",                        // 라벨 언어 ko|en
  "as_of": null,                       // 시점 조회(선택)
  "top_k": 12                          // 검색 후보 수 1~30
}
```
> **seeds(앵커링)**: `answer_segments`의 `cite` 토큰이나 finding `citations[]`의 `{source_type, source_id}`를 그대로 넣으면, 재검색에서 빠지더라도 클릭한 그 인용이 그래프에 **반드시 포함되고 강조**(`highlighted`)됩니다. seeds 없이 `text`만 보내도 동작(하위호환).

**응답** `RelatedGraphResponse`
```json
{
  "root": {"label": "입력 문구", "text": "국내 1위·100% 효과"},
  "issues": [
    {"label": "과장·허위 광고", "statute": "의료법 제56조", "statute_highlighted": true,
     "cases": [{"source_id": 20, "label": "대법원 2018두12345", "title": "...",
                "summary": "...", "source_url": "...", "highlighted": true}],
     "sanctions": ["업무정지 1개월"]}
  ],
  "method": "hybrid",   // hybrid|fts
  "llm": true           // false면 규칙 폴백 그래프
}
```
프론트는 `root → issues → cases/sanctions`를 노드, 그 부모-자식 관계를 엣지로 매핑하고 `highlighted`/`statute_highlighted`로 클릭한 노드를 강조합니다. → **[프론트 연동 가이드(JS 예제)](docs/frontend-related-graph.md)**

```bash
curl -s -X POST localhost:8077/v1/related-graph -H 'content-type: application/json' \
  -d '{"text":"국내 1위 100% 효과 과장 의료광고","seeds":[{"source_type":"case","source_id":20}]}'
```

---

### 6. `GET /v1/statutes/search` — 법령 검색 (코어, lawbot 호환)

조문 FTS를 법령 단위로. 쿼리 파라미터: `q`, `kind`(법률|대통령령|고시…), `trust_grade`, `as_of`, `limit`(1~100).
```bash
curl 'localhost:8077/v1/statutes/search?q=의료광고&limit=10'
```

---

### 6-B. `GET /v1/laws/*` — 법령 개정 현황 대시보드

법제처 국가법령정보 공동활용 데이터로 **4대 법령**(의료법·개인정보보호법·생명윤리법·정보통신망법)의 개정 타임라인을 추적. 구법 인용 리스크를 줄이는 게 목적(기획서 ⑤).

**데이터 적재(배치)** — `scripts/sync_revisions.py`를 1일 1회 cron으로. 각 법령의 전 버전(시행예정/현행/연혁)을 `law_revisions`에 idempotent upsert. 미동기화 상태로 API를 처음 부르면 라이브로 자동 부트스트랩.
```bash
LAW_OC=<발급키> DB_PATH=data/medilaw.db python scripts/sync_revisions.py            # 4대 법령
LAW_OC=<발급키> python scripts/sync_revisions.py --subordinate                       # +시행령·시행규칙
# cron 예: 30 4 * * * cd .../backend/fastapi && DB_PATH=data/medilaw.db python scripts/sync_revisions.py
```
> ⚠️ `LAW_OC` 키는 호출 **IP/도메인이 법제처에 등록**돼 있어야 응답함(미등록 시 HTML 에러 → `503`).

**① `GET /v1/laws/revisions`** — 대시보드 메인. 법령별 현행·시행예정·연혁 요약.
```jsonc
{ "laws": [{
    "law_id": "001788", "name": "의료법", "ministry": "보건복지부",
    "current": {"mst":"285327","effective_on":"2026-04-07","revision_type":"일부개정","reason":"[일부개정] ◇ 개정이유 ..."},
    "upcoming": [{"effective_on":"2026-09-11","revision_type":"타법개정","mst":"283899"}],  // ⚠ 앞으로 바뀔 조항
    "history_count": 87, "latest_effective_on": "2026-04-07"
  }], "tracked": 4, "synced_at": "2026-06-17T00:50:28+00:00" }
```

**② `GET /v1/laws/{law_id}/revisions`** — 한 법령 전체 개정 이력(시행일 내림차순, 각 버전의 `mst`·`effective_on`·`revision_type`·`status`).

**③ `GET /v1/laws/diff?law_id=&from=&to=`** — **개정 전후 조문 비교**. `from`/`to`는 ②의 `effective_on`(YYYYMMDD). 두 버전 조문을 받아 추가/삭제/변경 조문을 before/after로 반환(첫 호출만 법제처 조회 ~5s, 이후 캐시).
```bash
# 의료법 2020-03-28 → 현행 2026-04-07 (41개 조문 변경)
curl 'localhost:8077/v1/laws/diff?law_id=001788&from=20200328&to=20260407'
# → {added, removed, changed, diffs:[{article_no:"2", change:"changed", before:"...", after:"...「간호법」에 따른..."}]}
```

---

### 7. `GET /health`, `GET /` — 운영 (인증 없음)

`/health` → `{status, db_path, db_exists, db_size_mb, embeddings_ready, vec_extension, revisions_ready, auth_enabled, mcp_mounted}`. `/` → 기능 인덱스.

---

### 엔드유저(2개) vs 코어 구분

```
POST /chat/stream      ─┐
POST /documents/review  ┤ 내부에서
POST /chat/checklist   ─┴─▶ hybrid_search(/v1/retrieve 코어) + extract_and_verify(/v1/verify 코어) 호출
GET  /v1/laws/*         ───▶ 법제처 Open API(별도 계열, RAG 코어 안 씀)
```
- **React 프론트가 호출**: 🟢 `/chat/stream` · `/documents/review` · `/chat/checklist` + 대시보드 `/v1/laws/*`.
- `/v1/{retrieve,source-pack,verify,statutes/search}`: 위 🟢 들이 쓰는 **공유 코어**이자 **MCP·외부 에이전트용 API**. 프론트가 직접 부를 필요 없음(지우면 챗봇·에디터가 함께 죽음).
- `/v1/laws/*`(대시보드)는 RAG 코어가 아니라 **법제처 Open API**를 직접 호출하는 별도 계열.

---

## 공통 규약

**인증 헤더** — `API_KEYS` 설정 시 모든 엔드포인트(단 `/health`·`/` 제외)에 필수:
```
x-api-key: <발급키>
```
**에러 코드**

| 코드 | 상황 |
|---|---|
| 400 | (review) `file`·`text` 둘 다 없음 / 텍스트·OCR 모두 빈 PDF / (verify) `text`·`citations` 둘 다 없음 |
| 401 | `x-api-key` 누락·오류(`API_KEYS` 설정 시) |
| 429 | 분당 호출 한도 초과 |
| 503 | `OPENAI_API_KEY` 미설정 등 LLM 사용 불가(`/chat`·`/documents/review`) |

**호출 구조** — `React(브라우저) → Node(메인) → 이 FastAPI(AI)`. 프론트는 이 서버를 직접 부르지 않고 **Node가 서버-서버로 호출**한다. 그래서 CORS(브라우저 전용 규칙)는 불필요(미설정). Node는 아래 엔드포인트를 일반 HTTP로 호출하고, 인증을 켜면 `x-api-key` 헤더만 실으면 된다.

## Node 호출 예제

Node가 호출하는 🟢 엔드포인트(`/chat/stream`, `/documents/review`, `/chat/checklist`)의 호출 형태. 아래 `fetch` 스니펫은 Node(서버)에서 그대로 쓰며, 스트리밍은 Node가 받아 브라우저로 중계(passthrough)한다.

**① 챗봇 (SSE 스트리밍)** — `EventSource`는 GET만 되므로 POST는 `fetch` + `ReadableStream`으로 직접 파싱:
```js
async function streamChat(question, history = [], onToken, onDone) {
  const res = await fetch("http://localhost:8077/chat/stream", {
    method: "POST",
    headers: { "content-type": "application/json" /*, "x-api-key": KEY */ },
    body: JSON.stringify({ question, history, top_k: 8, lang: "auto" }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n");      // SSE 이벤트 경계
    buf = events.pop();                     // 미완성 조각은 다음 청크로
    for (const ev of events) {
      const line = ev.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const msg = JSON.parse(line.slice(5).trim());
      if (msg.type === "sources") onToken({ sources: msg.sources });        // 근거 먼저
      else if (msg.type === "token") onToken({ text: msg.text });            // 토큰 누적
      else if (msg.type === "done") onDone(msg.citation_check);              // 인용검증 결과
      else if (msg.type === "error") throw new Error(msg.message);
    }
  }
}
```
> 멀티턴: 응답을 받은 뒤 `history`에 `{role:"user",...}`·`{role:"assistant",...}`를 쌓아 다음 요청에 그대로 전달(서버 무상태). 최근 10턴만 사용됨.

**② PDF/텍스트 검토** — `multipart/form-data`(JSON 아님, `Content-Type` 자동 설정에 맡길 것):
```js
async function reviewDoc({ file, text, prevChecklist }) {
  const fd = new FormData();
  if (file) fd.append("file", file);        // <input type=file> 의 File
  if (text) fd.append("text", text);        // 또는 본문 직접
  if (prevChecklist) fd.append("prev_checklist", JSON.stringify(prevChecklist));
  const res = await fetch("http://localhost:8077/documents/review", {
    method: "POST", body: fd /*, headers: { "x-api-key": KEY } */,
  });
  return res.json(); // { original_text, revised_text, findings[], checklist[], ... }
}
```
> 렌더 힌트: `original_text`↔`revised_text` diff 뷰 · `findings[].risk_level`별 색칠 · `extracted_by==="ocr"`면 "OCR 인식" 배지 · `checklist`는 할 일 목록(`checklist_summary`로 진행률). 응답 필드 전체는 [엔드포인트 상세](#2-post-documentsreview--능동형-pdf-에디터-) 참고.

## 아키텍처

```
app/
  main.py        FastAPI 진입점 (/health, /, 라우터 등록)
  config.py      환경변수·상수 (모델/차원/RRF/인증)
  db.py          SQLite 공유 커넥션 + sqlite-vec 로드 시도
  auth.py        x-api-key 인증 + 분당 레이트리밋
  schemas.py     pydantic 요청/응답 계약
  rag.py         하이브리드 검색: FTS5(bm25) + 벡터(sqlite-vec/numpy) RRF 융합
  citations.py   Citation Firewall 핵심: 한국 법률 인용 파싱 + DB 대조
  routers/
    retrieve.py     POST /v1/retrieve, GET /v1/statutes/search
    source_pack.py  POST /v1/source-pack
    verify.py       POST /v1/verify
    related_graph.py POST /v1/related-graph (인용 클릭→연관 판례 엣지-노드 그래프)
    chat.py         POST /chat, POST /chat/stream, POST /chat/checklist (gpt-5.5 RAG 챗봇·체크리스트)
    documents.py    POST /documents/review(+/stream) (PDF→위험검토→before/after, OCR 실패 시 gpt-5.5 폴백)
    laws.py         GET /v1/laws/revisions·{law_id}/revisions·diff (법령 개정 현황 대시보드)
  related_graph.py 연관 판례 그래프 코어: hybrid_search→gpt-5.5 쟁점 클러스터링→Citation Firewall
  llm.py          OpenAI gpt-5.5 래퍼 (chat / chat_stream / chat_json / ocr_image / translate)
  english.py      영어 입력 지원: 언어감지 + 공식 영문 법령(articles_en) 조회
  lawapi.py       법제처 DRF 클라이언트(개정 연혁/버전·조문) + law_revisions 동기화·캐시
scripts/
  ingest_api.py        법제처 Open API → law/prec/admrul/expc/ppc 누적 수집(코퍼스 확장)
  ingest_guidelines.py 보건복지부 통합검색/게시판 → 가이드라인 PDF/HWPX/HWP 추출 → documents(guideline)
  dedup_documents.py   documents 본문 중복 제거(idempotent)
  build_embeddings.py  articles+cases+documents → chunks(+sqlite-vec) 임베딩 (incremental/rebuild)
  ingest_elaw.py       법제처 영문법령 API(target=elaw) → articles_en (영어 입력용 공식 영문)
  sync_revisions.py    법제처 → law_revisions 개정 타임라인 동기화(1일 1회 배치, 대시보드용)
mcp_server/
  server.py      MCP 서버 (retrieve/source_pack/verify/statutes_search 도구)
data/
  medilaw.db     law-app에서 복사 (cases 20,975 + articles 189,238 + statutes 3,438 + FTS5)
```

## 영어 입력 지원 (`lang=en`)

`/chat`·`/chat/stream`·`/documents/review` 는 `lang`(`auto`\|`ko`\|`en`)을 받습니다. `auto`는 입력의 한글 비율로 자동 감지.

영어 질의 흐름 (`app/english.py`):
```
EN 질문 → ① llm.translate(EN→KO)로 검색어 번역 (FTS는 한글 토큰이라 필수)
        → ② hybrid_search(KO 코퍼스)
        → ③ statute hit → articles_en 에서 공식 영문 조문 부착(label_en/snippet_en/is_official_en)
        → ④ gpt-5.5: 공식 영문 조문 인용 + 그 외(판례·해석례·가이드라인)는 비공식 번역 → 영어 답변
```
- **법령 = 공식 영문**: 법제처 영문법령 Open API(`target=elaw`)로 적재한 `articles_en` 사용 → 법령명·조문을 **공식 번역 그대로** 인용(환각·오역 방지). `ChatSource.is_official_en=true`.
- **판례·해석례·가이드라인 = 비공식 번역**: 공식 영문이 없어 LLM이 즉석 번역하고 `(unofficial translation)`으로 표기.
- 응답에 실제 사용 언어 `lang` 포함.

**영문 법령 적재** (최초 1회 / 개정 반영 시):
```bash
LAW_OC=H-Lab python3 scripts/ingest_elaw.py     # 4대법+시행령/규칙 영문 조문 → articles_en
```
> ⚠️ 한계: ① 영문판은 한국어 개정보다 **시행일이 뒤처질 수 있음**(`articles_en.eng_effective` 참고). ② Citation Firewall 정규식은 한국어 인용 기준이라 **영어 답변에선 검증 적중이 낮음**(근거 자체는 공식 영문이라 신뢰 가능). ③ 일부 시행규칙은 공식 영문 없음 → `[KO src]`로 표기.

## 검색 동작 (graceful degradation)

- 기본은 **FTS5(BM25)** 만으로 즉시 동작 — API 키 불필요.
- `OPENAI_API_KEY` 설정 + `build_embeddings.py` 실행 후 **chunks** 테이블이 생기면
  자동으로 **하이브리드(FTS+벡터 RRF)** 로 전환. `/health`의 `embeddings_ready`로 확인.
- 벡터 KNN은 `sqlite-vec`(설치 시) → 없으면 numpy 코사인 인메모리 폴백.
- **sub-chunk**: 긴 본문(가이드라인·긴 조문·긴 판례)은 ~1000자 조각으로 분할해 각각 임베딩 →
  대형 문서가 세부 질문에 희석되지 않음. 검색 시 문서 단위로 dedup하고 매칭 조각을 스니펫으로 반환.
  분할 임계/크기: env `SUB_MAX`(기본 1200)·`PIECE`(1000)·`OVERLAP`(120).

## 성능 (실측)

로컬 측정(`DB_PATH=data/medilaw.db`, 임베딩 빌드됨, gpt-5.5, **`REASONING_EFFORT=low`**):

| 동작 | 근거 도착 | 첫 토큰 | 완답 |
|---|---|---|---|
| `/chat/stream` 단발(짧은 질문) | ~1s | **~1.8s** | **~4.3s** |
| `/chat/stream` 멀티턴(질의 재작성 1회 추가) | ~2.4s | ~5.7s | ~8.1s |
| `/documents/review` 2문장 텍스트 | — | — | ~14s (세그먼트별 분석이라 분량 비례) |
| `/chat/checklist` (4턴 대화) | — | — | ~35s (쟁점추출 9s + RAG 5s + 생성 20s) |

- 가장 큰 변수는 gpt-5.5 생성 시간. `REASONING_EFFORT=low`로 **추론 강도를 낮춰 완답을 약 절반**으로 단축(근거 기반 답변이라 품질 영향 작음). `medium`/`high`로 올리면 품질↑·속도↓.
- 검색 자체(`/v1/retrieve`)는 임베딩 1회 + sqlite-vec로 **~0.6s**. 병목 아님.
- 멀티턴이 느린 건 답변 생성 전 **후속질문 재작성 LLM 1회**가 순차로 끼기 때문(검색 정확도 대가).
- 문서검토는 세그먼트마다 검색+분석이 돌아 **분량에 비례**, 스캔본은 비전 OCR이 앞에 더 붙음.
- `/chat/checklist`는 **쟁점추출(LLM)→RAG→생성(LLM)** 2회 순차 호출이라 가장 무겁다. 출처 수를 줄여도 생성은 **출력 토큰(항목 수)에 비례**해 안 줄어듦 → 버튼 1회성 종합 리포트로 설계(진행 표시 권장).

## 로컬 실행

```bash
pip install -r requirements.txt
DB_PATH=data/medilaw.db uvicorn app.main:app --host 127.0.0.1 --port 8077

# 한글 질의 (FTS 전용 상태에서도 동작)
curl -s -X POST localhost:8077/v1/retrieve \
  -H 'content-type: application/json' \
  -d '{"query":"무면허 의료행위","top_k":5}'

# Citation Firewall
curl -s -X POST localhost:8077/v1/verify \
  -H 'content-type: application/json' \
  -d '{"text":"의료법 제27조와 가짜 의료법 제999조","as_of":"2026-06-15"}'
```

## 코퍼스 확장 (법령·판례·해석례·결정문 더 가져오기)

법제처 Open API(`LAW_OC`, 기본 `H-Lab`)에서 추가 수집 → 누적(idempotent):

| target | 내용 | 저장 |
|---|---|---|
| `law` | 4대 법령 본문(+시행령/규칙) | statutes/articles (law_id upsert) |
| `prec` | 판례 | cases (seq_no/case_no dedup) |
| `admrul` | 행정규칙(고시·훈령·예규·지침) | statutes/articles (trust_grade B) |
| `expc` | 법령해석례 | documents(`interpretation`) |
| `ppc` | 개인정보보호위원회 결정문 | documents(`decision`) |
| `all` | 위 전부 | |

```bash
python3 scripts/ingest_api.py --target law
python3 scripts/ingest_api.py --target prec   --max 200
python3 scripts/ingest_api.py --target expc   --max 100
python3 scripts/ingest_api.py --target ppc    --query "민감정보" --max 100
python3 scripts/ingest_api.py --target admrul --max 100
python3 scripts/ingest_api.py --target all    --max 100
```
※ OC 키는 호출 IP/도메인 등록이 되어 있어야 응답함. expc/ppc는 `documents` 테이블(+`documents_fts`)에 적재되어
retrieve의 `source_types=["interpretation","decision"]`로 검색됨.

### 보건복지부 가이드라인 (법제처 API 밖 — 게시판 PDF/HWP)

법제처 API에 없는 보건복지부 가이드라인은 게시판 첨부에서 추출. **통합검색(`--search`) 권장** —
가이드라인이 여러 게시판(bid 0009/0019/0026/0027…)에 흩어져 있어 검색이 한 번에 가져옴:
```bash
# 통합검색(권장) — 제목 키워드 쉼표구분
python3 scripts/ingest_guidelines.py --search "의료광고 가이드라인,비의료 건강관리서비스,유전자검사 가이드라인,의료기관 개인정보보호 가이드라인"
# board 0026 제목 크롤 / 특정 게시물
python3 scripts/ingest_guidelines.py --keyword 가이드라인 --pages 30
python3 scripts/ingest_guidelines.py --list_no 1490826
# 수집 후 본문 중복 정리
python3 scripts/dedup_documents.py
```
→ `documents(doc_type='guideline')` 적재, `source_types=["guideline"]`로 검색.
지원 형식: **PDF·HWPX·DOCX·HWP**(구형 .hwp는 PrvText 미리보기라 부분 추출일 수 있음). 스캔본(이미지)은 OCR 필요(미지원).

## 임베딩 빌드 (하이브리드 활성화)

```bash
# incremental(기본) — 아직 임베딩 안 된 새 행만 (코퍼스 확장 후 권장)
OPENAI_API_KEY=sk-... python3 scripts/build_embeddings.py
# 전체 재생성
MODE=rebuild python3 scripts/build_embeddings.py
# 테스트: LIMIT=500 ONLY=statute
```
`text-embedding-3-small`(dim=512)로 articles 전문 + cases(case_name+issues+summary) 임베딩.
**확장 흐름: `ingest_api.py` → `build_embeddings.py`(incremental)** 로 DB·벡터가 함께 커짐.

## 인증 / 레이트리밋

- `API_KEYS=key1,key2` 설정 시 모든 `/v1` 요청에 `x-api-key` 헤더 필수.
- 미설정 시 인증 생략(로컬). 레이트리밋 `RATE_LIMIT_PER_MIN`(기본 30, IP/키별 분당).

## MCP 서버 — uvicorn 한 서버에 포함됨

MCP는 별도 프로세스가 아니라 **FastAPI 앱(`app/main.py`)에 `/mcp` SSE로 마운트**돼 있습니다.
`uvicorn app.main:app` 하나만 띄우면 REST 4개 + MCP가 같이 서비스됩니다(로컬·배포 동일).
`/health`의 `mcp_mounted`로 확인. 노출 도구(4): `retrieve`, `source_pack`, `verify`, `statutes_search`.

- 마운트 경로: `/mcp/sse`(연결), `/mcp/messages`(메시지)
- LLM 클라이언트(원격 URL 등록):
```json
{ "mcpServers": { "medilaw": { "url": "http://localhost:8077/mcp/sse" } } }
```
- (대안) stdio 단독 실행 — Claude Desktop이 자식 프로세스로:
```json
{ "mcpServers": { "medilaw": {
    "command": "python3", "args": ["-m", "mcp_server.server"],
    "cwd": "/home/user1/MediLaw/backend/fastapi",
    "env": {"DB_PATH": "data/medilaw.db", "OPENAI_API_KEY": "..."} } } }
```

> ⚠️ 의존성 주의: `mcp`(sse-starlette)는 `starlette>=0.49`를 요구하므로 `fastapi`도
> starlette 1.x를 허용하는 버전(현재 0.137)으로 맞춰야 합니다. `requirements.txt` 참고.

## 배포

`Dockerfile` 로 컨테이너화. DB는 git/도커 제외 → 볼륨에 업로드 후 `DB_PATH=/app/data/medilaw.db` 설정,
`OPENAI_API_KEY` 등은 env로. (`railway.toml` 은 제거함 — 이 디렉토리 단독 자동배포 안 함.)
이 서버는 Node(메인 백엔드)만 호출하므로 외부에 직접 노출하지 말 것(내부망/방화벽). 공개해야 하면 `API_KEYS`로 보호.

## 알려진 공백

- **보건복지부 가이드라인**: 통합검색으로 수집됨(의료광고·비의료 건강관리·DTC 유전자검사·의료기관 개인정보보호 등 24건). 구형 `.hwp`는 PrvText 부분 추출. (가이드라인 **코퍼스 수집** 스크립트는 스캔본 OCR 미지원 — 단, **`POST /documents/review` 엔드포인트는 스캔본 PDF를 비전 OCR로 처리함**, 별개.)
- 해석례(expc)·결정문(ppc)은 기본 DB엔 소량(검증분)만 → 필요 시 대량 수집.
- 같은 문서가 포맷(hwpx vs pdf)이 달라 추출 텍스트가 다르면 dedup이 못 잡음(내용은 거의 동일).
- 임베딩 빌드 전에는 FTS 전용이라 구어체 의미검색이 약함(빌드하면 해소).
- **개정 대시보드(`/v1/laws/*`)**: `LAW_OC` 키는 호출 **IP/도메인 등록** 필요(미등록 시 `503`/HTML). 법제처 `target=lsHistory`(연혁 전용)는 이 키로 막혀 `target=eflaw`(시행일 법령, 연혁+현행+시행예정 포함)로 우회 — 시행일 지정 조문(`efYd`)까지 돼 개정 전후 비교에 더 적합. 대시보드 **시각화 UI는 프론트/Node 몫**(이 백엔드는 데이터·비교 API만).

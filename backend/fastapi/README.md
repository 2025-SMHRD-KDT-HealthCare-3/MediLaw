# MediLaw API (FastAPI)

[lawbot.org](https://lawbot.org/)의 4대 기능을 의료 4법령 도메인으로 구현한 백엔드.
대상 법령: **의료법 · 개인정보 보호법 · 생명윤리법 · 정보통신망법** + 보건의료 행정규칙·판례.

> ⚠️ 작업 제1원칙: 이 디렉토리(`backend/fastapi`) 안에서만 작업 (`CLAUDE.md` 참고).

## 구현 현황

- [x] **RAG API / Source Pack / Citation Firewall / MCP**(4도구) — lawbot 4대 기능
- [x] **하이브리드 검색** FTS5 + OpenAI 임베딩(text-embedding-3-small, 512d) RRF, **sub-chunk**(대형 문서 분할)
- [x] **데이터**: 4대 법령+시행령/규칙, 행정규칙, 판례, **법령해석례·개인정보위 결정문·보건복지부 가이드라인**(의료광고 등) — 법제처 Open API + 게시판 수집기
- [x] **임베딩 빌드 완료** chunks 212,459 (sqlite-vec)
- [x] **AI 챗봇** `POST /chat`(+SSE) — gpt-5.5 RAG + Citation Firewall 검증
- [x] **능동형 PDF 에디터** `POST /documents/review` — 위험 탐지 + before/after 수정안, 스캔본 **비전 OCR** fallback
- [x] **영어 입력 지원** `lang=en` — 법령은 **공식 영문**(법제처 elaw API), 판례·해석례·가이드라인은 비공식 번역
- [ ] 프론트엔드(React 챗 UI) — 미구현(백엔드 API만)

## API 한눈에 보기

> 베이스 URL 예: `http://localhost:8077` · 문서(Swagger): `GET /docs`
> 인증: `API_KEYS` 설정 시 `x-api-key` 헤더 필수(미설정이면 생략). 분당 레이트리밋 적용.

| 분류 | 메서드 · 경로 | 용도 |
|---|---|---|
| 🟢 **프론트용** | `POST /chat/stream` | AI 질의응답 챗봇(SSE 스트리밍) |
| 🟢 **프론트용** | `POST /documents/review` | PDF/텍스트 위험 검토 + before/after 수정안 |
| 챗봇(단발) | `POST /chat` | 위와 동일, JSON 한 번에 반환(느림) |
| 코어 | `POST /v1/retrieve` | 하이브리드 RAG 검색 |
| 코어 | `POST /v1/source-pack` | LLM 인용용 근거 마크다운 번들 |
| 코어 | `POST /v1/verify` | Citation Firewall(인용 검증) |
| 코어 | `GET /v1/statutes/search` | 법령 검색(lawbot 호환) |
| 에이전트 | `/mcp/sse` | MCP 서버(4도구) — uvicorn에 마운트 |
| 운영 | `GET /health`, `GET /` | 상태 점검 / 기능 인덱스(인증 없음) |

> **프론트(React)는 🟢 두 개만 호출**하면 됩니다. 나머지 `/v1/*`는 이 두 엔드포인트가 내부에서 호출하는 코어이자, MCP/외부 에이전트용 표면입니다. → [엔드유저 vs 코어](#엔드유저2개-vs-코어-구분)

---

## 📖 API 엔드포인트 상세

### 1. `POST /chat/stream` — AI 챗봇 (SSE) 🟢

질문 → 하이브리드 근거검색 → **gpt-5.5** 답변(근거 `[n]` 강제 인용) → **Citation Firewall** 자동검증.
단발 JSON이 필요하면 동일 body로 `POST /chat`(아래 응답 본문과 같은 형태, gpt-5.5라 ~30s 소요 → UI는 스트리밍 권장).

**요청** `Content-Type: application/json`
```json
{
  "question": "병원 광고에 '국내 최초'라고 써도 되나요?",
  "top_k": 8,                  // 1~20, 검색 근거 수
  "source_types": null,        // ["statute","case","interpretation","decision","guideline"] 필터(선택)
  "as_of": null,               // "2024-01-01" 시점 조회(선택)
  "lang": "auto"               // auto|ko|en — en이면 영어로 답변(아래 "영어 입력 지원")
}
```

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
             "matched_label":"의료법 제56조","matched_source_url":"...","note":""}],
  "summary":{"total":1,"verified":1,"failed":0},"as_of":null}}
```
에러 시 `{"type":"error","message":"..."}`. ⚠️ 브라우저 `EventSource`는 GET만 지원 → POST는 `fetch` + `ReadableStream`으로 직접 파싱.

```bash
curl -N -X POST localhost:8077/chat/stream -H 'content-type: application/json' \
  -d '{"question":"병원 광고에 \"국내 최초\" 표현 써도 되나요?","top_k":5}'
```

---

### 2. `POST /documents/review` — 능동형 PDF 에디터 🟢

문서(PDF/텍스트) → 텍스트 추출(**스캔본은 비전 OCR fallback**) → 세그먼트 분할 → 세그먼트별 RAG → **gpt-5.5** 위험 분석 → Citation Firewall.
결과로 **before/after**(원문 ↔ 수정본)와 위험 세그먼트별 사유·대안·근거를 돌려줍니다.

**요청** `Content-Type: multipart/form-data` — `file`(PDF) **또는** `text` 중 하나 필수

| 필드 | 필수 | 설명 |
|---|---|---|
| `file` | ▲ | 검토할 PDF |
| `text` | ▲ | PDF 대신 본문 직접 입력 |
| `as_of` | – | 시점 조회 `YYYY-MM-DD` |
| `top_k_per_segment` | – | 세그먼트별 근거 수(기본 4, 1~8) |
| `lang` | – | `auto`\|`ko`\|`en` — 영문 문서 검토 시 `en`(아래 "영어 입력 지원") |

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
  "extracted_by": "ocr",     // "text"=디지털 PDF / "ocr"=스캔본 비전 OCR
  "citation_check": {"output":[],"summary":{"total":0,"verified":0,"failed":0}},
  "method": "hybrid",
  "as_of": null
}
```
- **프론트 렌더**: `original_text`↔`revised_text` diff 뷰 / `findings[].segment_index`로 `segments[]`에서 위험 조각을 찾아 `risk_level`별 색칠 → 클릭 시 사유·대안·근거 패널 / `extracted_by==="ocr"`면 "OCR 인식(오인식 가능)" 배지.

```bash
curl -X POST localhost:8077/documents/review -F "file=@ad.pdf"
curl -X POST localhost:8077/documents/review -F "text=부작용 전혀 없는 100% 안전한 시술"
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
**응답** `{"output":[VerifyResult...],"summary":{"total":2,"verified":1,"failed":1},"as_of":"2026-06-15"}`
`VerifyResult = {raw, type(statute|case|unknown), exists, clause_accurate, valid_as_of, verified, matched_label, matched_source_url, note}`

---

### 6. `GET /v1/statutes/search` — 법령 검색 (코어, lawbot 호환)

조문 FTS를 법령 단위로. 쿼리 파라미터: `q`, `kind`(법률|대통령령|고시…), `trust_grade`, `as_of`, `limit`(1~100).
```bash
curl 'localhost:8077/v1/statutes/search?q=의료광고&limit=10'
```

---

### 7. `GET /health`, `GET /` — 운영 (인증 없음)

`/health` → `{status, db_path, db_exists, db_size_mb, embeddings_ready, vec_extension, auth_enabled, mcp_mounted}`. `/` → 기능 인덱스.

---

### 엔드유저(2개) vs 코어 구분

```
POST /chat/stream     ─┐ 내부에서
POST /documents/review ─┴─▶ hybrid_search(/v1/retrieve 코어) + extract_and_verify(/v1/verify 코어) 호출
```
- **React 프론트**: `/chat/stream`, `/documents/review` **2개만** 호출.
- `/v1/*`(retrieve·source-pack·verify·statutes/search): 위 둘이 쓰는 **공유 코어**이자 **MCP·외부 에이전트용 API**. 프론트가 직접 부를 필요 없음(지우면 챗봇·에디터가 함께 죽음).

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
    chat.py         POST /chat, POST /chat/stream (gpt-5.5 RAG 챗봇)
    documents.py    POST /documents/review (PDF→위험검토→before/after, 비전 OCR fallback)
  llm.py          OpenAI gpt-5.5 래퍼 (chat / chat_stream / chat_json / ocr_image / translate)
  english.py      영어 입력 지원: 언어감지 + 공식 영문 법령(articles_en) 조회
scripts/
  ingest_api.py        법제처 Open API → law/prec/admrul/expc/ppc 누적 수집(코퍼스 확장)
  ingest_guidelines.py 보건복지부 통합검색/게시판 → 가이드라인 PDF/HWPX/HWP 추출 → documents(guideline)
  dedup_documents.py   documents 본문 중복 제거(idempotent)
  build_embeddings.py  articles+cases+documents → chunks(+sqlite-vec) 임베딩 (incremental/rebuild)
  ingest_elaw.py       법제처 영문법령 API(target=elaw) → articles_en (영어 입력용 공식 영문)
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

## 알려진 공백

- **보건복지부 가이드라인**: 통합검색으로 수집됨(의료광고·비의료 건강관리·DTC 유전자검사·의료기관 개인정보보호 등 24건). 구형 `.hwp`는 PrvText 부분 추출. (가이드라인 **코퍼스 수집** 스크립트는 스캔본 OCR 미지원 — 단, **`POST /documents/review` 엔드포인트는 스캔본 PDF를 비전 OCR로 처리함**, 별개.)
- 해석례(expc)·결정문(ppc)은 기본 DB엔 소량(검증분)만 → 필요 시 대량 수집.
- 같은 문서가 포맷(hwpx vs pdf)이 달라 추출 텍스트가 다르면 dedup이 못 잡음(내용은 거의 동일).
- 임베딩 빌드 전에는 FTS 전용이라 구어체 의미검색이 약함(빌드하면 해소).

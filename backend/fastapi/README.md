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
- [ ] PDF 문서 에디터(기획서 ②) — 미구현
- [ ] 프론트엔드(React 챗 UI) — 미구현(백엔드 API만)

## 4대 기능

| # | 기능 | 엔드포인트 | 설명 |
|---|---|---|---|
| 1 | **RAG API** | `POST /v1/retrieve` | 조문·판례·해석례 통합 **하이브리드 검색**(FTS5 + 벡터 RRF), clause-level, `as_of` 시점 조회 |
| 2 | **Source Pack** | `POST /v1/source-pack` | 질의 → 관련 근거를 **LLM 인용용 마크다운** 번들로 |
| 3 | **Citation Firewall** | `POST /v1/verify` | AI 답변의 인용을 DB와 대조(법령 존재·조문 정확성·판례 유효성·시점) |
| 4 | **MCP Server** | `/mcp/sse` (uvicorn에 마운트) | Claude/Cursor에 위 기능을 에이전트 도구로 노출. stdio 단독 실행(`python -m mcp_server.server`)도 지원 |

보조: `GET /v1/statutes/search`(lawbot 호환), `GET /health`, `GET /docs`(Swagger).

## AI 챗봇 (기획서 핵심기능 ①)

| 기능 | 엔드포인트 | 설명 |
|---|---|---|
| **AI 질의응답 챗봇** | `POST /chat`, `POST /chat/stream`(SSE) | 질문 → hybrid 근거검색 → **gpt-5.5** 답변(근거 [n] 인용) → **Citation Firewall 자동검증** |

흐름: `hybrid_search → gpt-5.5(근거만 사용·환각금지·[n]인용) → extract_and_verify(답변)`.
응답: `{answer, sources[n,label,snippet,url], citation_check{output,summary}}`. 근거 없으면 추측 없이 "확인 불가".
스트리밍 이벤트: `sources` → `token`×N → `done`(citation_check). 생성 LLM은 `config.CHAT_MODEL`(기본 gpt-5.5).
```bash
curl -s -X POST localhost:8077/chat -H 'content-type: application/json' \
  -d '{"question":"병원 광고에 \"국내 최초\" 표현 써도 되나요?","top_k":5}'
```

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
  llm.py          OpenAI gpt-5.5 래퍼 (chat / chat_stream)
scripts/
  ingest_api.py        법제처 Open API → law/prec/admrul/expc/ppc 누적 수집(코퍼스 확장)
  ingest_guidelines.py 보건복지부 통합검색/게시판 → 가이드라인 PDF/HWPX/HWP 추출 → documents(guideline)
  dedup_documents.py   documents 본문 중복 제거(idempotent)
  build_embeddings.py  articles+cases+documents → chunks(+sqlite-vec) 임베딩 (incremental/rebuild)
mcp_server/
  server.py      MCP 서버 (retrieve/source_pack/verify/statutes_search 도구)
data/
  medilaw.db     law-app에서 복사 (cases 20,975 + articles 189,238 + statutes 3,438 + FTS5)
```

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

- **보건복지부 가이드라인**: 통합검색으로 수집됨(의료광고·비의료 건강관리·DTC 유전자검사·의료기관 개인정보보호 등 24건). 구형 `.hwp`는 PrvText 부분 추출, 스캔본은 OCR 필요(미지원).
- 해석례(expc)·결정문(ppc)은 기본 DB엔 소량(검증분)만 → 필요 시 대량 수집.
- 같은 문서가 포맷(hwpx vs pdf)이 달라 추출 텍스트가 다르면 dedup이 못 잡음(내용은 거의 동일).
- 임베딩 빌드 전에는 FTS 전용이라 구어체 의미검색이 약함(빌드하면 해소).

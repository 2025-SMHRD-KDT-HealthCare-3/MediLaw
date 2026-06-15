# MediLaw AI Backend

MediLaw AI 프로젝트의 FastAPI 백엔드입니다.

현재 백엔드는 사용자 계정, JWT 인증, 대화방, 채팅, AI 답변 mock 흐름, 응답 근거, AI 검증, 의료광고 문구 검토, 대화 요약, 관리자 조회 API를 제공합니다.

lawbot, 실제 OpenAI 호출, 실제 외부 법령 API, 실제 RAG 검색은 아직 연결하지 않았습니다. 해당 영역은 `app/ai` 폴더의 mock/stub 함수를 실제 구현으로 교체하는 방식으로 확장합니다.

## 기술 스택

- Python 3.x
- FastAPI
- MySQL
- SQLAlchemy
- Alembic
- Pydantic
- JWT
- bcrypt
- pytest

현재 개발 환경에서는 설치된 Python 버전으로 테스트를 통과했습니다. 특정 기능에서 Python 3.12가 꼭 필요한 구조는 아직 없습니다.

## 실행 방법

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

서버 체크:

```bash
curl http://127.0.0.1:8000/server-check
curl http://127.0.0.1:8000/api/server-check
```

테스트 실행:

```bash
python -m pytest
```

현재 확인된 테스트 결과:

```text
10 passed
```

## 환경변수

`.env.example`을 `.env`로 복사한 뒤 값을 설정합니다.

```env
ENVIRONMENT=local
DATABASE_URL=mysql+pymysql://medilaw:medilaw@localhost:3306/medilaw
JWT_SECRET_KEY=replace-with-secure-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
OPENAI_API_KEY=
LAW_API_KEY=
UPLOAD_DIR=storage/uploads
CORS_ORIGINS=*
```

주의:

- 운영 환경에서는 `JWT_SECRET_KEY`를 반드시 안전한 값으로 변경해야 합니다.
- `ENVIRONMENT=production` 또는 `prod`에서 기본 JWT secret을 사용하면 앱이 실행되지 않도록 방어했습니다.
- `CORS_ORIGINS=*`는 개발용입니다. 운영에서는 프론트엔드 도메인을 명시하세요.
- `OPENAI_API_KEY`는 현재 인증 확인은 가능하지만, 실제 AI 답변 생성에는 아직 사용하지 않습니다.

## 폴더 구조

```text
backend/
  app/
    main.py
    core/
    models/
    schemas/
    repositories/
    services/
    ai/
    routers/
    utils/
  migrations/
  storage/
    uploads/
  tests/
  alembic.ini
  pytest.ini
  requirements.txt
  .env.example
  README.md
```

주요 역할:

- `app/main.py`: FastAPI 앱 생성, CORS, 라우터 등록, 서버 체크
- `app/core`: 설정, DB 연결, 보안, 공통 의존성, 예외, 응답 포맷
- `app/models`: SQLAlchemy ORM 모델
- `app/schemas`: Pydantic 요청/응답 스키마와 입력 검증
- `app/repositories`: DB CRUD 접근 계층
- `app/services`: 권한 확인, 트랜잭션, 비즈니스 로직
- `app/routers`: API 엔드포인트
- `app/ai`: lawbot, RAG, 외부 법령 API, OpenAI 연동 경계. 현재는 mock/stub
- `app/utils`: 공통 유틸리티
- `migrations`: Alembic 마이그레이션
- `storage`: 업로드 파일 참조용 로컬 저장 위치
- `tests`: pytest 테스트

## DB 저장 원칙

관계형 DB에는 사용자 중심 이력 데이터만 저장합니다.

DB에 직접 저장하지 않는 데이터:

- 법령 원문
- 판례 원문
- 행정해석 원문
- 외부 API 응답 원문
- 첨부 파일 원본 bytes

만들지 않는 테이블:

- `law_articles`
- `law_masters`
- `law_revisions`
- `precedents`
- `external_api_raw_logs`
- `ai_responses`

AI 답변 저장 원칙:

- AI 답변도 `tb_chat`에 저장합니다.
- AI 답변은 `speaker_type='AI'`로 구분합니다.
- 별도 `ai_responses` 테이블은 사용하지 않습니다.
- `tb_evidence.ans_id`는 AI 답변이 저장된 `tb_chat.chat_id`를 참조합니다.
- `tb_verification.ans_id`도 AI 답변이 저장된 `tb_chat.chat_id`를 참조합니다.

파일 저장 원칙:

- `tb_chat.chat_file`에는 파일 원본이 아니라 파일명 또는 파일 참조 경로만 저장합니다.
- `tb_summary.summary_file`에도 파일 원본이 아니라 파일명 또는 파일 참조 경로만 저장합니다.
- 파일 참조 경로는 절대경로와 `../` 경로를 차단합니다.

## 테이블 설명

- `tb_user`: 사용자 계정, 로그인 ID, 비밀번호 해시, 이름, 연락처, 이메일, 권한
- `tb_room`: 대화방 정보. `room_limit`은 ERD 명칭을 유지하며 방 인원수 또는 제한 인원 수로 사용
- `tb_chat`: USER, AI, ADMIN 발화 저장. AI 답변도 이 테이블에 저장
- `tb_evidence`: AI 답변에 사용된 법령명, 조문번호, 핵심 근거, 출처 URL 저장
- `tb_verification`: AI 답변 검증 결과 저장
- `tb_ai_ad_copy`: 의료광고/서비스 문구 검토 결과 저장
- `tb_summary`: 대화 요약, 체크리스트, 관리자 확인 여부 저장

## 구현된 API

인증:

- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/logout`

사용자:

- `GET /api/users/me`
- `PATCH /api/users/me`

대화방:

- `POST /api/rooms`
- `GET /api/rooms`
- `GET /api/rooms/{room_id}`
- `PATCH /api/rooms/{room_id}`

채팅:

- `GET /api/rooms/{room_id}/chats`
- `POST /api/rooms/{room_id}/chats`

AI 답변:

- `POST /api/rooms/{room_id}/ai-answer`

응답 근거:

- `GET /api/answers/{ans_id}/evidences`

AI 검증:

- `GET /api/answers/{ans_id}/verifications`
- `POST /api/answers/{ans_id}/verify`

AI 광고 카피:

- `POST /api/ai-ad-copies`
- `GET /api/ai-ad-copies`
- `GET /api/ai-ad-copies/{ai_copy_id}`

대화 요약:

- `POST /api/rooms/{room_id}/summaries`
- `GET /api/rooms/{room_id}/summaries`
- `PATCH /api/summaries/{summary_id}/confirm`

관리자:

- `GET /api/admin/users?skip=0&limit=100`
- `GET /api/admin/verifications?skip=0&limit=100`
- `GET /api/admin/summaries?skip=0&limit=100`

## 현재 구현 상태

구현 완료:

- 회원가입 시 `login_id`, `email` 중복 검사
- bcrypt 기반 비밀번호 해시 저장
- JWT access token 발급과 인증
- `/api/users/me` 인증 사용자 조회/수정
- 관리자 권한 의존성
- 대화방 생성/조회/수정
- 본인 대화방 접근 권한 검사
- 채팅 저장/조회
- `CLOSED` 상태 방의 신규 채팅/AI 답변 차단
- AI 답변 mock 흐름
- AI 답변 저장, evidence 저장, verification 저장을 하나의 트랜잭션으로 처리
- 응답 근거 조회
- AI 검증 조회와 mock 재검증
- 광고 카피 mock 분석 결과 저장/조회
- 관리자 전용 요약 생성/확인
- 관리자 목록 조회 API
- 입력 검증
- 파일 참조 경로 검증
- Alembic 마이그레이션 구성
- pytest 기반 테스트

아직 mock/stub인 영역:

- 실제 OpenAI 답변 생성
- 실제 외부 법령 API 조회
- 실제 RAG 검색
- 실제 조문 검증
- 실제 의료광고 법률 검토
- 실제 대화 요약 생성

## lawbot 연동 기준

lawbot 팀은 `app/ai` 폴더를 중심으로 실제 기능을 교체하면 됩니다.

현재 연결 지점:

- `llm_client.py`
- `rag_service.py`
- `law_api_client.py`
- `citation_extractor.py`
- `citation_verifier.py`
- `ad_copy_analyzer.py`
- `summary_generator.py`

연동 시 지켜야 할 원칙:

- 원문 법령/판례/행정해석/외부 API 원문 응답은 DB에 저장하지 않습니다.
- 저장이 필요한 경우 `tb_evidence`에는 법령명, 조문번호, 핵심 근거, 출처 URL만 저장합니다.
- AI 답변은 계속 `tb_chat`에 `speaker_type='AI'`로 저장합니다.
- `tb_evidence.ans_id`, `tb_verification.ans_id`는 AI 답변의 `tb_chat.chat_id`를 사용합니다.

## Alembic

현재 `migrations/versions`에 초기 스키마 정렬용 migration 파일이 있습니다.

DB 반영:

```bash
alembic upgrade head
```

새 마이그레이션 생성:

```bash
alembic revision --autogenerate -m "message"
```

주의:

- 운영 DB 반영 전에는 migration 내용을 반드시 확인해야 합니다.
- 기존 캠퍼스 DB의 제약조건 이름, comment, server default 차이 때문에 `alembic check`에서 비기능 diff가 나올 수 있습니다.

## 남은 TODO

- 실제 OpenAI API 호출 연결
- lawbot 실제 법령 API/RAG/조문 검증 연결
- refresh token 또는 token blacklist 기반 logout 정책
- 관리자 운영 액션 확장
  - 사용자 권한 변경
  - 방 종료/재개 정책
  - 광고 카피 검토 상태 관리
  - 요약 반려/수정 정책
- 운영 배포용 CORS 도메인 설정
- 운영 DB 기준 통합 테스트
- API 응답 스키마 문서화 고도화

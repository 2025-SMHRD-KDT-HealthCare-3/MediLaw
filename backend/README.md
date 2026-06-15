# MediLaw AI Backend

MediLaw AI 프로젝트의 FastAPI 백엔드 기본 구조입니다. 현재 단계의 목적은 실제 기능 완성이 아니라 DB 설계와 기능 구조에 맞는 모델, 스키마, 레포지토리, 서비스, 라우터, AI mock/stub 계층을 준비하는 것입니다.

## 기술 스택

- Python 3.12
- FastAPI
- MySQL
- SQLAlchemy
- Alembic
- Pydantic
- JWT 인증
- passlib/bcrypt 비밀번호 해시

## 실행 방법

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

상태 확인:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/health
```

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
  storage/uploads/
  tests/
  alembic.ini
  requirements.txt
  .env.example
```

## DB 저장 원칙

관계형 DB에는 사용자 중심 이력 데이터만 저장합니다. 법령 원문, 판례 원문, 행정해석 원문, 외부 API 응답 원문은 MySQL DB에 직접 저장하지 않습니다. 법령 조회, 조문 검증, 광고 문구 검토 과정에서 필요한 외부 데이터는 외부 API 또는 임시 처리 영역에서 처리합니다.

채팅 또는 요약에 첨부된 파일 원본은 DB에 저장하지 않고, 파일명 또는 파일 참조 경로만 저장합니다. `law_articles`, `law_masters`, `law_revisions`, `precedents`, `external_api_raw_logs`, `ai_responses` 테이블은 만들지 않습니다.

AI 답변도 `tb_chat` 테이블에 저장합니다. `tb_evidence.ans_id`와 `tb_verification.ans_id`는 별도 AI 답변 테이블의 ID가 아니라, AI 답변이 저장된 `tb_chat.chat_id`를 참조합니다.

## 테이블 설명

- `tb_user`: 사용자 계정, 권한, 연락처 정보
- `tb_room`: 사용자별 대화방 정보. `room_limit`은 ERD 명칭을 유지하며 방 인원수 또는 제한 인원 수로 사용
- `tb_chat`: USER, AI, ADMIN 발화 저장. AI 답변도 이 테이블에 저장
- `tb_evidence`: AI 답변에 사용된 법령명, 조문번호, 핵심근거, 출처 URL 저장
- `tb_verification`: AI 답변의 조문 존재 여부, 내용 일치 여부, 시행일 유효성, 검증 상태, 신뢰점수 저장
- `tb_ai_ad_copy`: 의료광고/서비스 문구 검토 결과 저장
- `tb_summary`: 대화 요약, 체크리스트, 관리자 확인 여부 저장

## API 목록

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

응답근거:

- `GET /api/answers/{ans_id}/evidences`

AI 검증:

- `GET /api/answers/{ans_id}/verifications`
- `POST /api/answers/{ans_id}/verify`

AI 광고 카피 수정:

- `POST /api/ai-ad-copies`
- `GET /api/ai-ad-copies`
- `GET /api/ai-ad-copies/{ai_copy_id}`

대화 요약:

- `POST /api/rooms/{room_id}/summaries`
- `GET /api/rooms/{room_id}/summaries`
- `PATCH /api/summaries/{summary_id}/confirm`

관리자:

- `GET /api/admin/users`
- `GET /api/admin/verifications`
- `GET /api/admin/summaries`

## Alembic

초기 마이그레이션 생성:

```bash
alembic revision --autogenerate -m "create initial tables"
alembic upgrade head
```

## 구현 주의사항

현재 `app/ai` 계층은 실제 OpenAI API, 외부 법령 API, RAG를 호출하지 않습니다. 모든 함수는 mock/stub입니다. 실제 연동 단계에서도 외부 법령 API 원문 응답이나 법령 전문을 MySQL에 저장하지 않도록 유지해야 합니다.

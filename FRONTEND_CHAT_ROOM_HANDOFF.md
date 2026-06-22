# 프론트 연동 메모: 챗봇 방/대화 흐름

## 핵심 원칙

프론트는 HMS/RAG를 직접 호출하지 않고 Node 브리지를 통해 제품 app API만 호출합니다.

```text
React -> Node bridge /api/* -> Product app -> HMS/RAG -> Product app DB 저장 -> React
```

챗봇 대화에서 직접 호출하면 안 되는 경로:

```text
POST /api/rag/chat
POST /api/rag/chat/stream
POST /api/rag/chat/checklist
```

위 경로는 DB 저장을 우회하므로 Node에서 차단됩니다. 챗봇 질문은 반드시 아래 제품 API를 사용합니다.

```text
POST /api/rooms/{room_id}/ai-answer
```

## 인증

Node 로그인은 제품 app 로그인 응답의 access token을 `session` httpOnly cookie로 저장합니다.

```http
POST /api/auth/login
```

프론트 주의사항:

- fetch/axios 요청에 cookie가 포함되도록 설정해야 합니다.
- fetch: `credentials: 'include'`
- axios: `withCredentials: true`
- access token을 응답 body에서 직접 꺼내 쓰는 방식으로 구현하지 않습니다.

로그아웃:

```http
POST /api/auth/logout
```

## 새 상담 시작

```http
POST /api/rooms
Content-Type: application/json
```

예시 body:

```json
{
  "room_title": "새 의료법 상담",
  "room_desc": "선택 입력"
}
```

응답의 `data.room_id`를 이후 챗봇 질문에 사용합니다.

## 이전 상담 목록

```http
GET /api/rooms
```

현재 로그인 유저의 대화방 목록을 반환합니다. 일반 유저는 본인 방만 조회됩니다.

## 특정 상담 대화 불러오기

```http
GET /api/rooms/{room_id}/chats
```

화면 표시용 기존 대화 목록입니다. AI 답변 생성에 쓰는 history와 다릅니다.

- 화면 조회: 이 API로 기존 대화 표시
- AI 답변 생성: 백엔드가 같은 room_id의 최근 10개 메시지만 HMS에 전달

## 질문 전송

```http
POST /api/rooms/{room_id}/ai-answer
Content-Type: application/json
```

예시 body:

```json
{
  "question": "병원 광고에 100% 안전하다고 써도 되나요?"
}
```

응답에는 사용자 질문, AI 답변, 근거, 검증 결과가 포함됩니다.

```text
data.question_chat
data.answer_chat
data.evidences
data.verifications
```

백엔드는 이 요청에서 다음 저장을 처리합니다.

```text
tb_chat: USER 질문
tb_chat: AI 답변
tb_evidence: 답변 근거
tb_verification: 검증 결과
```

## 나가기

```http
POST /api/rooms/{room_id}/leave
```

나가기는 화면 이탈 개념입니다.

- DB 변경 없음
- room_status는 ACTIVE 유지
- 나중에 같은 room_id로 다시 들어와 이어서 질문 가능

## 상담 종료

```http
POST /api/rooms/{room_id}/close
```

상담 종료는 room을 닫습니다.

- room_status가 CLOSED로 변경됨
- 기존 대화 조회 가능
- 새 질문/AI 답변 생성 불가

프론트에서는 확인 모달을 권장합니다.

```text
상담을 종료하면 이 방에서는 더 이상 질문할 수 없습니다. 기존 대화는 보관됩니다.
```

## 대화방 삭제

```http
DELETE /api/rooms/{room_id}
```

삭제는 실제 삭제입니다.

삭제 대상:

```text
tb_verification
tb_evidence
tb_summary
tb_chat
tb_room
```

프론트에서는 확인 모달을 반드시 권장합니다.

```text
삭제하면 대화 내용과 근거 기록을 다시 볼 수 없습니다.
```

## 상태별 UI 권장

```text
ACTIVE
- 질문 입력 가능
- 나가기 가능
- 상담 종료 가능
- 삭제 가능

CLOSED
- 기존 대화 조회 가능
- 질문 입력 비활성화
- 나가기 가능
- 삭제 가능
```

## 프론트에서 특히 주의할 점

1. 챗봇 질문에 `/api/rag/*`를 사용하지 않습니다.
2. 방을 새로 시작할 때는 먼저 `POST /api/rooms`로 room_id를 받아야 합니다.
3. 기존 상담을 이어갈 때만 기존 room_id를 사용합니다.
4. 나가기와 상담 종료를 같은 버튼으로 묶지 않습니다.
5. 삭제는 상담 종료와 다른 동작입니다. 삭제는 기록 복구가 안 됩니다.
6. Node 브리지를 통과하므로 API base는 같은 origin의 `/api`로 잡으면 됩니다.

# [Node 담당 인계] 레이트리밋·실사용자 식별

작성: 2026-06-26 · 대상: **Node(메인 백엔드) 담당** · 출처: fastapi 전체 코드 리뷰

전체 백엔드 리뷰에서 나온 항목 중 **fastapi가 아니라 Node에서 처리해야 하는 것**을 정리한다.
(fastapi 쪽에서 할 수 있는 보완은 이미 반영했고, 아래는 Node 작업이다.)

---

## 핵심 문제

호출 구조가 **React → Node → FastAPI**(서버-서버)다. 그래서 FastAPI 입장에서는
모든 요청이 **Node 서버 IP 하나**로 들어온다. 결과적으로:

- FastAPI의 IP 기반 레이트리밋(`app/auth.py`)은 **무인증 모드에서 전체 트래픽을 하나의 버킷**으로
  묶는다 → 한 사용자가 분당 한도(`RATE_LIMIT_PER_MIN`, 기본 30)를 다 쓰면 **모든 사용자**가 429.
- API 키 모드에서도 Node는 **하나의 서비스 키**로 FastAPI를 호출하므로, FastAPI 레벨에서는
  실사용자 단위 구분이 불가능하다(모든 사용자가 그 키 버킷을 공유).

즉 **실사용자(세션/회원) 단위 레이트리밋과 인증은 사용자 신원을 아는 Node에서 해야 한다.**
FastAPI 레이트리밋은 "서비스 전체 보호용 거친 가드"로만 동작한다.

---

## Node가 해야 할 일

### 1) 실사용자 단위 레이트리밋 (필수)
Node는 로그인 세션/회원 ID를 알고 있으니, **사용자(또는 세션) 단위로 분당 호출 한도**를
Node에서 적용한다. (예: 사용자별 토큰버킷/슬라이딩윈도우, Redis 등 공유 스토어 권장 —
Node도 여러 인스턴스면 인메모리는 인스턴스별로 갈리므로 부정확.)

### 2) (선택) 실제 클라이언트 IP 전달
FastAPI가 거친 IP 가드를 그래도 유지하려면, Node가 FastAPI 호출 시
**`X-Forwarded-For` 헤더에 실제 클라이언트 IP**를 실어 보내면 된다.
FastAPI는 이미 **XFF 첫 IP를 레이트리밋 식별자로 우선 사용**하도록 반영해 두었다
(`app/auth.py` `require_api_key`). Node가 XFF를 안 보내면 기존처럼 Node IP 하나로 묶인다.

```
# Node → FastAPI 요청 헤더 예
X-Forwarded-For: <원래 클라이언트 IP>
x-api-key: <서비스 키>            # API_KEYS 설정 시
```

### 3) 인증 게이트는 Node에서 (필수)
FastAPI의 `API_KEYS`는 **서비스 키**(Node↔FastAPI 구간 보호)일 뿐, 실사용자 인증이 아니다.
또한 `API_KEYS` 미설정 시 FastAPI는 **무인증 공개**(fail-open, 개발 모드)다.
따라서:
- **사용자 로그인/권한 검사는 Node에서** 끝내고, FastAPI는 Node 뒤에서만 접근 가능해야 한다
  (FastAPI를 외부에 직접 노출 금지).
- 운영 배포 시 FastAPI `API_KEYS`를 **반드시 설정**해 Node↔FastAPI 구간을 잠근다.

---

## 참고: FastAPI 쪽에서 이미 반영한 보완
- `require_api_key`가 `X-Forwarded-For` 첫 IP를 레이트리밋 식별자로 우선 사용.
- 레이트리밋 상태(`_calls`)의 만료 항목 주기적 정리(메모리 누수 방지).
- 위 동작과 한계를 `app/auth.py` docstring에 명시.

질문은 fastapi 담당에게.

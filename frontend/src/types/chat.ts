// src/types/chat.ts

// 인용(Citation)의 검증 상태 — 화면설계서의 확인/주의/오류와 1:1 매핑
export type CitationStatus = 'verified' | 'caution' | 'error';

// 답변이 인용한 법령 1건의 정보
export interface Citation {
  id: string;
  no?: number;            // 답변 본문의 인용 번호 [n] (evidences 원래 1-based 순번)
  lawName: string;        // 예: "의료법 제56조"
  clause: string;         // 인용된 조문 내용
  status: CitationStatus; // 확인 / 주의 / 오류
  reason?: string;        // 검증 사유 (백엔드 verification_reason, 있을 경우)
  sourceUrl?: string;     // 원문 링크 (있을 경우)
}

// 메시지 한 개 (사용자 질문 또는 AI 답변)
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';  // 누가 보낸 메시지인지
  content: string;             // 메시지 본문
  timestamp: string;           // ISO 문자열 (예: "2026-06-17T11:46:00")
  citations?: Citation[];      // AI 답변에만 붙음 (사용자 메시지엔 없음)
  trustScore?: number;         // 0~100, AI 답변의 신뢰 점수
}
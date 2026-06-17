// src/mocks/mockChat.ts
import type { ChatMessage } from '../types/chat';

// 채팅 화면 미리보기용 가짜 데이터
// 나중에 백엔드 연결되면 이 배열 대신 API 응답을 쓰면 됨
export const mockMessages: ChatMessage[] = [
  {
    id: 'm1',
    role: 'user',
    content: '환자에게 "이 시술은 100% 안전합니다"라고 안내해도 될까요?',
    timestamp: '2026-06-17T11:40:00',
  },
  {
    id: 'm2',
    role: 'assistant',
    content:
      '"100% 안전" 같은 단정적 표현은 의료광고 심의 기준에 저촉될 수 있습니다. ' +
      '치료 효과를 보장하거나 과장하는 표현은 의료법상 금지 대상에 해당할 가능성이 높습니다.',
    timestamp: '2026-06-17T11:40:08',
    trustScore: 87,
    citations: [
      {
        id: 'c1',
        lawName: '의료법 제56조',
        clause: '의료광고에서 치료효과를 보장하는 등 소비자를 현혹할 우려가 있는 내용의 광고는 금지된다.',
        status: 'verified',
      },
      {
        id: 'c2',
        lawName: '의료법 시행령 제23조',
        clause: '거짓이나 과장된 내용의 의료광고에 해당할 수 있어 추가 검토가 필요합니다.',
        status: 'caution',
      },
    ],
  },
];
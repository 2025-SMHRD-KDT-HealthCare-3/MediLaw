// src/components/chat/ChatMessage.tsx
import type { ChatMessage as ChatMessageType } from '../../types/chat';
import CitationBadge from './CitationBadge';
import TrustScore from './TrustScore';
import { useLang } from '../../i18n/LanguageContext';

interface ChatMessageProps {
  message: ChatMessageType;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const { t } = useLang();
  const isUser = message.role === 'user';

  // 1) 사용자 질문 → 오른쪽, navy 말풍선
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-navy px-4 py-2.5 text-sm text-white">
          {message.content}
        </div>
      </div>
    );
  }

  // 2) AI 답변 → 왼쪽, 흰 카드 + 신뢰점수 + 근거 법령
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] space-y-3">
        {/* 답변 본문 */}
        <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 text-sm leading-relaxed text-gray-800">
          {message.content}
        </div>

        {/* 신뢰 점수 — trustScore가 있을 때만 */}
        {message.trustScore !== undefined && (
          <div className="px-1">
            <TrustScore score={message.trustScore} />
          </div>
        )}

        {/* 근거 법령 — citations가 있을 때만 */}
        {message.citations && message.citations.length > 0 && (
          <div className="space-y-2">
            <p className="px-1 text-xs font-semibold text-gray-500">{t('chat.evidenceLabel')}</p>
            {message.citations.map((c) => (
              <div key={c.id} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-navy">{c.lawName}</span>
                  <CitationBadge status={c.status} />
                </div>
                <p className="text-xs leading-relaxed text-gray-600">{c.clause}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
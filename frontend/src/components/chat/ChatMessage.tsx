// src/components/chat/ChatMessage.tsx
import type { ReactNode } from 'react';
import type { ChatMessage as ChatMessageType } from '../../types/chat';
import CitationBadge from './CitationBadge';
import TrustScore from './TrustScore';
import { useLang } from '../../i18n/LanguageContext';

interface ChatMessageProps {
  message: ChatMessageType;
}

// ── 챗봇 답변용 경량 마크다운 렌더러 ─────────────────────────────────────────
// 외부 라이브러리 없이, HMS(챗봇 프롬프트)가 내보내는 세 가지 형식만 처리한다:
//   1) 빈 줄로 구분된 문단        → 각각 <p> 로 분리 (줄바꿈이 살아남)
//   2) '- ' 로 시작하는 줄        → <ul><li> 불릿 목록으로 묶음
//   3) **굵게**                   → <strong> (조문명·소제목 강조)
// ※ HMS 프롬프트는 위 세 형식에 맞춰 출력해야 한다(바탕화면 지시서 참고).
function renderInline(text: string): ReactNode[] {
  // **굵게** 구간을 <strong> 으로. 나머지는 그대로.
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    return bold ? (
      <strong key={i} className="font-semibold text-navy">
        {bold[1]}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    );
  });
}

function MarkdownLite({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  let key = 0;

  const flushBullets = () => {
    if (bullets.length === 0) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={`ul-${key++}`} className="list-disc space-y-1 pl-5">
        {items.map((item, i) => (
          <li key={i}>{renderInline(item)}</li>
        ))}
      </ul>,
    );
  };

  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-•]\s+(.*)$/); // '- ' 또는 '• ' 불릿
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    flushBullets();
    if (line.trim() === '') continue; // 빈 줄 → 문단 사이 간격(space-y)으로 표현
    blocks.push(<p key={`p-${key++}`}>{renderInline(line)}</p>);
  }
  flushBullets();

  return <div className="space-y-2">{blocks}</div>;
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

  // 2) AI 답변 → 왼쪽, 흰 카드 + (신뢰점수 좌 · 근거 법령 우)
  const hasEvidence = !!message.citations && message.citations.length > 0
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] space-y-3">
        {/* 답변 본문 — 경량 마크다운 렌더링(문단/불릿/굵게) */}
        <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 text-sm leading-relaxed text-gray-800">
          <MarkdownLite text={message.content} />
        </div>

        {/* 신뢰도(좌) + 근거 법령(우) — 한 줄 배치. 카드는 컴팩트(한 줄 요약)하고,
            클릭하면 원문(법령·판례 등)이 새 탭으로 열린다. */}
        {(message.trustScore !== undefined || hasEvidence) && (
          <div className="flex gap-3">
            {message.trustScore !== undefined && (
              <div className="flex-shrink-0 pt-0.5">
                <TrustScore score={message.trustScore} />
              </div>
            )}

            {hasEvidence && (
              <div className="min-w-0 flex-1 space-y-1.5">
                <p className="text-xs font-semibold text-gray-500">{t('chat.evidenceLabel')}</p>
                {message.citations!.map((c) => {
                  const clause = (c.clause ?? '').trim()
                  const inner = (
                    <>
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-navy">
                          {c.lawName}
                          {c.sourceUrl && <span className="ml-1 text-[10px] text-aqua">↗</span>}
                        </span>
                        <CitationBadge status={c.status} />
                      </div>
                      {clause && (
                        <p className="mt-0.5 truncate text-[11px] leading-relaxed text-gray-500">
                          {clause}
                        </p>
                      )}
                    </>
                  )
                  return c.sourceUrl ? (
                    <a
                      key={c.id}
                      href={c.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="block rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 transition hover:border-aqua hover:bg-white"
                    >
                      {inner}
                    </a>
                  ) : (
                    <div
                      key={c.id}
                      className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5"
                    >
                      {inner}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
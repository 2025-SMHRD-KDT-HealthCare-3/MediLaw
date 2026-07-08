// src/components/chat/ChatMessage.tsx
import { useState } from 'react';
import type { ReactNode } from 'react';
import type { ChatMessage as ChatMessageType, Citation, CitationStatus } from '../../types/chat';
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

// ── 근거 법령 목록(접이식) ────────────────────────────────────────────────────
// 기본은 접힌 상태(카드 8개가 항상 펼쳐져 있으면 답변이 묻힘).
//   1단계: 헤더(근거 N개) 클릭 → 목록 펼침/접힘
//   2단계: 카드 클릭 → 카드 아래 상세 패널(조문 전문 + 상태 설명 + 원문 보기)
// 원문(새 탭) 이동은 상세 패널의 '원문 보기 →' 링크로만 일어난다.
// ※ 상태별 설명 문구는 i18n strings.ts 수정이 범위 밖이라 로컬에 둔다.
const statusNote: Record<'ko' | 'en', Record<CitationStatus, string>> = {
  ko: {
    verified: '코퍼스와 일치 확인됨',
    caution: '일부 불일치·확인 필요',
    error: '근거 불일치 가능성',
  },
  en: {
    verified: 'Matched against the law corpus',
    caution: 'Partial mismatch — needs review',
    error: 'Possible mismatch with the source',
  },
};

function EvidenceList({ citations }: { citations: Citation[] }) {
  const { t, lang } = useLang();
  const locale: 'ko' | 'en' = lang === 'en' ? 'en' : 'ko';
  const [open, setOpen] = useState(false);          // 목록 전체 펼침 여부 (기본: 접힘)
  const [expandedId, setExpandedId] = useState<string | null>(null); // 상세가 열린 카드 id

  return (
    <div className="min-w-0 flex-1 space-y-1.5">
      {/* 헤더: 근거 N개 + 셰브런 토글 */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-left text-xs font-semibold text-gray-500 transition hover:text-navy"
      >
        <span
          className={`inline-block text-[10px] transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
        >
          ▸
        </span>
        {t('chat.evidenceLabel')}
        {locale === 'ko' ? ` ${citations.length}개` : ` (${citations.length})`}
      </button>

      {open &&
        citations.map((c) => {
          const clause = (c.clause ?? '').trim();
          const expanded = expandedId === c.id;
          return (
            <div
              key={c.id}
              className={`rounded-lg border bg-gray-50 transition ${
                expanded ? 'border-aqua bg-white' : 'border-gray-200 hover:border-aqua hover:bg-white'
              }`}
            >
              {/* 카드(요약 줄) — 클릭하면 상세 패널 토글. 바로 이동하지 않는다. */}
              <button
                type="button"
                onClick={() => setExpandedId(expanded ? null : c.id)}
                aria-expanded={expanded}
                className="block w-full px-3 py-1.5 text-left"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-navy">
                    {/* 답변 본문의 [n]과 카드를 대조할 수 있게 원래 인용 번호를 앞에 표시 */}
                    {c.no !== undefined && (
                      <span className="mr-1 font-mono text-xs text-aqua">[{c.no}]</span>
                    )}
                    {c.lawName}
                  </span>
                  <CitationBadge status={c.status} />
                </div>
                {clause && !expanded && (
                  <p className="mt-0.5 truncate text-xs leading-relaxed text-gray-500">
                    {clause}
                  </p>
                )}
              </button>

              {/* 상세 패널: 조문 전문 + 상태 설명 + 원문 보기 */}
              {expanded && (
                <div className="space-y-2 border-t border-gray-100 px-3 py-2">
                  {clause && (
                    <p className="whitespace-pre-line text-xs leading-relaxed text-gray-600">
                      {clause}
                    </p>
                  )}
                  {/* 검증 사유: 백엔드가 준 실제 사유(reason) 우선, 없으면 상태별 고정 문구 */}
                  <div className="flex items-start gap-2">
                    <CitationBadge status={c.status} />
                    <span className="text-xs text-gray-500">
                      {(c.reason ?? '').trim() || statusNote[locale][c.status]}
                    </span>
                  </div>
                  {c.sourceUrl && (
                    <a
                      href={c.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-aqua transition hover:underline"
                    >
                      {locale === 'ko' ? '원문 보기' : 'View source'} →
                    </a>
                  )}
                </div>
              )}
            </div>
          );
        })}
    </div>
  );
}

export default function ChatMessage({ message }: ChatMessageProps) {
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

        {/* 신뢰도(좌) + 근거 법령(우) — 한 줄 배치. 근거 목록은 접이식이며,
            카드 클릭 → 상세 패널, 원문 이동은 상세의 '원문 보기 →' 링크로만. */}
        {(message.trustScore !== undefined || hasEvidence) && (
          <div className="flex gap-3">
            {message.trustScore !== undefined && (
              <div className="flex-shrink-0 pt-0.5">
                <TrustScore score={message.trustScore} />
              </div>
            )}

            {hasEvidence && <EvidenceList citations={message.citations!} />}
          </div>
        )}
      </div>
    </div>
  );
}
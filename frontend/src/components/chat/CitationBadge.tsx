// src/components/chat/CitationBadge.tsx
import type { CitationStatus } from '../../types/chat';
import { useLang } from '../../i18n/LanguageContext';

interface CitationBadgeProps {
  status: CitationStatus;
}

// 뱃지 한 종류가 가질 스타일 (라벨 번역키 + 색)
type BadgeStyle = {
  labelKey: string;
  box: string;
  dot: string;
};

// status 값 → 스타일 매핑
const statusConfig: Record<CitationStatus, BadgeStyle> = {
  verified: { labelKey: 'citation.verified', box: 'bg-confirmed/10 text-confirmed border-confirmed/30', dot: 'bg-confirmed' },
  caution:  { labelKey: 'citation.caution', box: 'bg-warning/10 text-warning border-warning/30',       dot: 'bg-warning' },
  error:    { labelKey: 'citation.error', box: 'bg-error/10 text-error border-error/30',               dot: 'bg-error' },
};

export default function CitationBadge({ status }: CitationBadgeProps) {
  const { t } = useLang();
  const { labelKey, box, dot } = statusConfig[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${box}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {t(labelKey)}
    </span>
  );
}
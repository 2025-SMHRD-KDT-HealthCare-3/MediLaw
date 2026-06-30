import { useEffect, useState, type CSSProperties } from 'react'
import { fetchLawRevisions } from '../api/lawApi'
import { useLang } from '../i18n/LanguageContext'
import type { LawItem, LawRevision } from '../types/lawUpdate'

const NAVY = '#14304A'
const AQUA = '#22C9DB'
const SUBBLUE = '#4A90D9'

// 상태 뱃지: 디자인 토큰 navy/subblue만 사용 (teal/amber/red는 citation 검증 전용)
const statusCurrentStyle: CSSProperties = { backgroundColor: NAVY, color: '#fff' }

const fmt = (d: string | null) => (d ? d.replace(/-/g, '.') : '-')

// 긴 reason에서 핵심만: '◇ 개정이유 및 주요내용' 이후 첫 문단, 없으면 앞 120자
// (reason 본문은 백엔드 데이터이므로 번역하지 않고, 비어 있을 때의 안내 문구만 fallback으로 받음)
function summarize(reason: string, missingText: string): string {
  if (!reason.trim()) return missingText
  const cleaned = reason
    .replace(/^\[.*?\]\s*/s, '')          // 맨 앞 [일부개정] 류 제거
    .replace(/<법제처 제공>\s*$/s, '')     // 꼬리 제거
    .trim()
  const firstPara = cleaned.split('\n').find((l) => l.trim() && !l.startsWith('◇'))
  const text = (firstPara ?? cleaned).trim()
  return text.length > 140 ? text.slice(0, 140) + '…' : text
}

export default function LawUpdates() {
  const { lang, t } = useLang()
  const [laws, setLaws] = useState<LawItem[]>([])
  const [syncedAt, setSyncedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    fetchLawRevisions()
      .then((data) => {
        setLaws(data.laws)
        setSyncedAt(data.synced_at)
      })
      .catch((e) => {
        console.error(e)
        setError(t('law.loadFailed'))
      })
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 시행예정 총 건수 (앞으로 바뀔 게 몇 개인지 — 차별점 강조 지표)
  const upcomingTotal = laws.reduce((sum, l) => sum + l.upcoming.length, 0)

  if (loading) {
    return <div className="grid min-h-[calc(100vh-60px)] place-items-center text-slate-400">{t('common.loading')}</div>
  }
  if (error) {
    return <div className="grid min-h-[calc(100vh-60px)] place-items-center text-slate-500">{error}</div>
  }

  return (
    <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
      <div className="mx-auto max-w-3xl">
        {/* 헤더 */}
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: NAVY }}>{t('law.title')}</h1>
            <p className="mt-1 text-sm text-slate-500">{t('law.tracking').replace('{count}', String(laws.length))}</p>
          </div>
          {upcomingTotal > 0 && (
            <div className="rounded-full px-4 py-2 text-sm font-semibold" style={{ backgroundColor: NAVY, color: '#fff' }}>
              {t('law.upcomingBadge').replace('{count}', String(upcomingTotal))}
            </div>
          )}
        </div>
        {syncedAt && (
          <p className="mb-6 text-xs text-slate-400">
            {t('law.syncedAt').replace('{time}', new Date(syncedAt).toLocaleString(lang === 'en' ? 'en-US' : 'ko-KR'))}
          </p>
        )}

        {/* 법령별 카드 */}
        <div className="space-y-5">
          {laws.map((law) => (
            <div key={law.law_id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              {/* 법령명 + 부처 */}
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-bold" style={{ color: NAVY }}>{law.name}</h2>
                  <p className="mt-0.5 text-xs text-slate-400">{law.ministry}</p>
                </div>
                <span className="text-xs text-slate-400">{t('law.revisionCount').replace('{count}', String(law.history_count))}</span>
              </div>

              {/* 현행 (current) */}
              {law.current && (
                <div className="mt-4 border-l-2 pl-4" style={{ borderColor: AQUA }}>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full px-2 py-0.5 text-xs font-medium" style={statusCurrentStyle}>{t('law.statusCurrent')}</span>
                    <span className="text-sm font-semibold" style={{ color: NAVY }}>
                      {t('law.effectiveOn').replace('{date}', fmt(law.current.effective_on))}
                    </span>
                    <span className="text-xs text-slate-400">{law.current.revision_type}</span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-slate-700">{summarize(law.current.reason, t('law.reasonMissing'))}</p>
                  <div className="mt-2 flex items-center gap-3">
                    <a href={law.current.detail_url} target="_blank" rel="noreferrer"
                       className="text-xs font-medium" style={{ color: SUBBLUE }}>
                      {t('law.viewSource')}
                    </a>
                    {law.upcoming.length > 0 && (
                      <button onClick={() => setOpenId(openId === law.law_id ? null : law.law_id)}
                              className="text-xs font-medium" style={{ color: SUBBLUE }}>
                        {openId === law.law_id ? t('law.closeUpcoming') : t('law.openUpcoming').replace('{count}', String(law.upcoming.length))}
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* 시행예정 (upcoming) 타임라인 */}
              {openId === law.law_id && law.upcoming.length > 0 && (
                <div className="mt-4 space-y-2 rounded-lg bg-slate-50 p-3">
                  {[...law.upcoming]
                    .sort((a, b) => (a.effective_on ?? '').localeCompare(b.effective_on ?? ''))
                    .map((u: LawRevision) => (
                      <div key={u.mst + u.effective_on} className="flex items-center gap-3 text-sm">
                        <span className="font-medium" style={{ color: SUBBLUE }}>{fmt(u.effective_on)}</span>
                        <span className="text-slate-500">{u.revision_type}</span>
                        <a href={u.detail_url} target="_blank" rel="noreferrer"
                           className="ml-auto text-xs text-slate-400 hover:underline">{t('law.sourceShort')}</a>
                      </div>
                    ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
import { useEffect, useState } from 'react'
import { getRooms } from '../api/chat'
import { getRoomSummaries, createRoomSummary, parseSummary, type ChecklistView } from '../api/checklistApi'
import { useLang } from '../i18n/LanguageContext'
import type { ChecklistItem, ChecklistStatus } from '../types/checklist'

const NAVY = '#14304A'
const SUBBLUE = '#4A90D9'
// 검증 상태 전용 토큰 (브랜드 색과 절대 혼용 금지)
const TEAL = '#13AAA0'   // confirmed
const AMBER = '#E8A33D'  // warning
const RED = '#D9534F'    // error

// status → 색 + 라벨 번역키 (라벨은 렌더 시 t()로 변환)
const statusMeta: Record<ChecklistStatus, { labelKey: string; color: string }> = {
  ok:   { labelKey: 'checklist.statusOk',   color: TEAL },
  todo: { labelKey: 'checklist.statusTodo', color: AMBER },
  risk: { labelKey: 'checklist.statusRisk', color: RED },
  na:   { labelKey: 'checklist.statusNa',   color: '#94A3B8' },
}

export default function Checklist() {
  const { t } = useLang()
  const [data, setData] = useState<ChecklistView | null>(null)
  const [roomId, setRoomId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)        // 진입 시 DB 조회
  const [generating, setGenerating] = useState(false) // 생성 진행
  const [error, setError] = useState('')
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  // 진입 시: 최신 방의 '저장된' 체크리스트를 DB에서 불러온다.
  // (예전처럼 매번 RAG로 새로 생성하지 않는다. 저장된 게 없으면 생성 버튼만 보여준다.)
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        setLoading(true)
        setError('')

        const roomsRes = await getRooms()
        const rooms = roomsRes?.data ?? []
        if (rooms.length === 0) {
          if (alive) setError(t('checklist.noRoom'))
          return
        }
        const latest = rooms[0]
        if (alive) setRoomId(latest.room_id)

        const summaries = await getRoomSummaries(latest.room_id)
        if (alive) setData(summaries.length > 0 ? parseSummary(summaries[0]) : null)
      } catch (e) {
        console.error('체크리스트 조회 실패:', e)
        if (alive) setError(t('checklist.loadFailed'))
      } finally {
        if (alive) setLoading(false)
      }
    }

    load()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 버튼: 생성 + 즉시 저장 → 화면 표시. 재진입 시엔 위 load가 DB에서 그대로 불러온다.
  const handleGenerate = async () => {
    if (!roomId || generating) return
    try {
      setGenerating(true)
      setError('')
      const rec = await createRoomSummary(roomId)
      setData(parseSummary(rec))
    } catch (e: unknown) {
      console.error('체크리스트 생성 실패:', e)
      const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message
      // 방에 대화이력이 없으면 백엔드가 'room has no chat history'를 반환
      setError(msg?.includes('history') ? t('checklist.emptyHistory') : (msg ?? t('checklist.genFailed')))
    } finally {
      setGenerating(false)
    }
  }

  const toggle = (id: string) => setChecked((c) => ({ ...c, [id]: !c[id] }))

  // 공통 헤더 (제목 줄)
  const Header = () => (
    <div className="mb-6 flex items-center justify-between">
      <h1 className="text-2xl font-bold" style={{ color: NAVY }}>{t('checklist.title')}</h1>
    </div>
  )

  // 진입 로딩 (DB 조회 중)
  if (loading) {
    return (
      <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
        <div className="mx-auto max-w-2xl">
          <Header />
          <div className="flex flex-col items-center justify-center py-28">
            <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200"
                 style={{ borderTopColor: NAVY }} />
            <p className="mt-4 text-sm font-medium" style={{ color: NAVY }}>{t('checklist.loadingSaved')}</p>
          </div>
        </div>
      </div>
    )
  }

  // 생성 진행 중
  if (generating) {
    return (
      <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
        <div className="mx-auto max-w-2xl">
          <Header />
          <div className="flex flex-col items-center justify-center py-28">
            <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200"
                 style={{ borderTopColor: NAVY }} />
            <p className="mt-4 text-sm font-medium" style={{ color: NAVY }}>{t('checklist.generating')}</p>
            <p className="mt-1 text-xs text-slate-400">{t('checklist.generatingSub')}</p>
          </div>
        </div>
      </div>
    )
  }

  // 에러 상태
  if (error) {
    return (
      <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
        <div className="mx-auto max-w-2xl">
          <Header />
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
            <p className="text-sm text-slate-500">{error}</p>
            {roomId && (
              <button
                onClick={handleGenerate}
                className="mt-4 rounded-lg px-5 py-2 text-sm font-medium text-white"
                style={{ backgroundColor: NAVY }}
              >
                {t('checklist.generate')}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // 저장된 체크리스트가 없음 → 생성 안내 + 버튼 (자동 생성하지 않음)
  if (!data) {
    return (
      <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
        <div className="mx-auto max-w-2xl">
          <Header />
          <div className="rounded-xl border border-slate-200 bg-white p-10 text-center">
            <p className="text-sm text-slate-500">{t('checklist.empty')}</p>
            <button
              onClick={handleGenerate}
              className="mt-5 rounded-lg px-6 py-2.5 text-sm font-medium text-white"
              style={{ backgroundColor: NAVY }}
            >
              {t('checklist.generate')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const s = data.summary
  const doneCount = data.checklist.filter((i) => checked[i.id] || i.status === 'ok').length

  return (
    <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
      <div className="mx-auto max-w-2xl">
        {/* 헤더 */}
        <div className="mb-1 flex items-center justify-between">
          <h1 className="text-2xl font-bold" style={{ color: NAVY }}>{t('checklist.title')}</h1>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-400">{t('checklist.autoGen')}</span>
          </div>
        </div>
        <p className="mb-6 text-sm text-slate-500">{t('checklist.desc')}</p>

        {/* 진행 요약 */}
        <div className="mb-6 flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex-1">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium" style={{ color: NAVY }}>{t('checklist.progress')}</span>
              <span className="text-slate-500">{doneCount} / {s.total}</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full" style={{ width: `${s.total ? (doneCount / s.total) * 100 : 0}%`, backgroundColor: TEAL }} />
            </div>
          </div>
          <div className="flex gap-3 text-center text-xs">
            <div><div className="text-lg font-bold" style={{ color: RED }}>{s.risk}</div><div className="text-slate-400">{t('checklist.riskShort')}</div></div>
            <div><div className="text-lg font-bold" style={{ color: AMBER }}>{s.todo}</div><div className="text-slate-400">{t('checklist.todoShort')}</div></div>
            <div><div className="text-lg font-bold" style={{ color: TEAL }}>{s.ok}</div><div className="text-slate-400">{t('checklist.doneShort')}</div></div>
          </div>
        </div>

        {/* 점검 항목 */}
        <div className="space-y-3">
          {data.checklist.map((item: ChecklistItem) => {
            const meta = statusMeta[item.status]
            const isChecked = checked[item.id] || item.status === 'ok'
            return (
              <div key={item.id} className="rounded-xl border border-slate-200 bg-white p-4"
                   style={{ borderLeft: `3px solid ${meta.color}` }}>
                <div className="flex items-start gap-3">
                  <button onClick={() => toggle(item.id)}
                          className="mt-0.5 grid h-5 w-5 flex-shrink-0 place-items-center rounded border"
                          style={{ borderColor: isChecked ? TEAL : '#CBD5E1', backgroundColor: isChecked ? TEAL : '#fff' }}>
                    {isChecked && <span className="text-xs text-white">✓</span>}
                  </button>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium" style={{ color: NAVY, textDecoration: isChecked ? 'line-through' : 'none', opacity: isChecked ? 0.5 : 1 }}>
                        {item.title}
                      </span>
                      <span className="rounded-full px-2 py-0.5 text-xs font-medium"
                            style={{ color: meta.color, backgroundColor: `${meta.color}1a` }}>
                        {t(meta.labelKey)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-600">{item.reason}</p>
                    {item.citations.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {item.citations.map((c) => (
                          <a key={c.n} href={c.source_url} target="_blank" rel="noreferrer"
                             className="rounded px-2 py-0.5 text-xs"
                             style={{ color: SUBBLUE, backgroundColor: '#EEF4FB' }}>
                            {c.label}
                          </a>
                        ))}
                      </div>
                    )}
                    {item.note && <p className="mt-1 text-xs text-slate-400">{item.note}</p>}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

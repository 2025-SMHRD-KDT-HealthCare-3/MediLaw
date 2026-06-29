import { useEffect, useState } from 'react'
import { getRooms, getChats } from '../api/chat'
import { generateChecklist } from '../api/checklistApi'
import type {
  ChecklistItem,
  ChecklistStatus,
  ChecklistResponse,
  ChatTurn,
} from '../types/checklist'

const NAVY = '#14304A'
const SUBBLUE = '#4A90D9'
// 검증 상태 전용 토큰 (브랜드 색과 절대 혼용 금지)
const TEAL = '#13AAA0'   // confirmed
const AMBER = '#E8A33D'  // warning
const RED = '#D9534F'    // error

// status → 표시 라벨 + 색
const statusMeta: Record<ChecklistStatus, { label: string; color: string }> = {
  ok:   { label: '확인 완료', color: TEAL },
  todo: { label: '확인 필요', color: AMBER },
  risk: { label: '위험',      color: RED },
  na:   { label: '해당 없음', color: '#94A3B8' },
}

export default function Checklist() {
  const [data, setData] = useState<ChecklistResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let alive = true

    const run = async () => {
      try {
        setLoading(true)
        setError('')

        // 1. 가장 최근 상담방 찾기
        const roomsRes = await getRooms()
        const rooms = roomsRes?.data ?? []
        if (rooms.length === 0) {
          if (alive) setError('분석할 상담 내역이 없어요. 먼저 챗봇에서 상담을 진행해주세요.')
          return
        }
        // 최신 방 (목록 첫 번째가 최신이라고 가정, 아니면 created_at 정렬)
        const latestRoom = rooms[0]

        // 2. 그 방의 대화 가져와서 ChatTurn[]으로 변환
        const chatsRes = await getChats(latestRoom.room_id)
        const chats = chatsRes?.data ?? []
        const history: ChatTurn[] = chats.map((c: { speaker_type: string; chat_text: string }) => ({
          role: c.speaker_type === 'USER' ? 'user' : 'assistant',
          content: c.chat_text,
        }))

        if (history.length === 0) {
          if (alive) setError('대화 내역이 비어 있어요. 챗봇에서 질문을 먼저 해주세요.')
          return
        }

        // 3. 체크리스트 생성 요청 (수~수십 초 소요)
        const res = await generateChecklist({ history, lang: 'ko' })
        if (alive) setData(res)
      } catch (e) {
        console.error('체크리스트 생성 실패:', e)
        if (alive) setError('체크리스트 생성에 실패했어요. 잠시 후 다시 시도해주세요.')
      } finally {
        if (alive) setLoading(false)
      }
    }

    run()
    return () => {
      alive = false
    }
  }, [])

  const toggle = (id: string) => setChecked((c) => ({ ...c, [id]: !c[id] }))

  // 로딩 상태
  if (loading) {
    return (
      <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
        <div className="mx-auto flex max-w-2xl flex-col items-center justify-center py-32">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200"
               style={{ borderTopColor: NAVY }} />
          <p className="mt-4 text-sm font-medium" style={{ color: NAVY }}>체크리스트 생성 중…</p>
          <p className="mt-1 text-xs text-slate-400">대화를 분석하고 있어요. 수십 초 걸릴 수 있어요.</p>
        </div>
      </div>
    )
  }

  // 에러 / 빈 상태
  if (error || !data) {
    return (
      <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
        <div className="mx-auto max-w-2xl">
          <h1 className="mb-6 text-2xl font-bold" style={{ color: NAVY }}>법령 준수 체크리스트</h1>
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
            <p className="text-sm text-slate-500">{error || '데이터를 불러오지 못했어요.'}</p>
          </div>
        </div>
      </div>
    )
  }

  const s = data.checklist_summary
  const doneCount = data.checklist.filter((i) => checked[i.id] || i.status === 'ok').length

  return (
    <div className="min-h-[calc(100vh-60px)] bg-slate-50 px-6 py-8">
      <div className="mx-auto max-w-2xl">
        {/* 헤더 */}
        <div className="mb-1 flex items-center justify-between">
          <h1 className="text-2xl font-bold" style={{ color: NAVY }}>법령 준수 체크리스트</h1>
          <span className="text-sm text-slate-400">대화 기반 자동 생성</span>
        </div>
        <p className="mb-6 text-sm text-slate-500">
          상담 내용을 분석해 확인이 필요한 법적 의무를 점검 항목으로 정리했습니다.
        </p>

        {/* 진행 요약 */}
        <div className="mb-6 flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex-1">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium" style={{ color: NAVY }}>점검 진행</span>
              <span className="text-slate-500">{doneCount} / {s.total}</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full" style={{ width: `${s.total ? (doneCount / s.total) * 100 : 0}%`, backgroundColor: TEAL }} />
            </div>
          </div>
          <div className="flex gap-3 text-center text-xs">
            <div><div className="text-lg font-bold" style={{ color: RED }}>{s.risk}</div><div className="text-slate-400">위험</div></div>
            <div><div className="text-lg font-bold" style={{ color: AMBER }}>{s.todo}</div><div className="text-slate-400">확인필요</div></div>
            <div><div className="text-lg font-bold" style={{ color: TEAL }}>{s.ok}</div><div className="text-slate-400">완료</div></div>
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
                        {meta.label}
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
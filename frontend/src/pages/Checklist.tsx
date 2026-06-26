import { useState, type CSSProperties } from 'react'
import { mockChecklist } from '../mocks/mockChecklist'
import type { ChecklistItem, ChecklistStatus } from '../types/checklist'

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
  // 백엔드 500 고쳐지면 generateChecklist(history) 결과로 교체
  const [data] = useState(mockChecklist)
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  const toggle = (id: string) => setChecked((c) => ({ ...c, [id]: !c[id] }))

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
              <div className="h-full rounded-full" style={{ width: `${(doneCount / s.total) * 100}%`, backgroundColor: TEAL }} />
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
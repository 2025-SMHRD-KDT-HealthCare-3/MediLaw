import { useEffect, useState } from 'react'

// 다운로드 페이지처럼 '진행 중'을 보여주는 대기 화면.
// 끝나는 시점을 알 수 없으므로 가짜 %는 쓰지 않고, 움직이는 표시 + 경과 시간 + 단계 안내로
// "무작정 멈춘 게 아니라 작동 중"임을 알린다.
const NAVY = '#14304A'

export default function LoadingWait({
  title,
  hint,
  expected,
  steps,
  compact = false,
}: {
  title: string
  hint?: string
  expected?: string // 예상 소요(예: "보통 1~4분 걸려요")
  steps?: string[] // 순환 표시할 단계 문구(선택)
  compact?: boolean
}) {
  const [elapsed, setElapsed] = useState(0)
  const [stepIdx, setStepIdx] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!steps || steps.length === 0) return
    const t = setInterval(() => setStepIdx((i) => (i + 1) % steps.length), 2500)
    return () => clearInterval(t)
  }, [steps])

  const elapsedText =
    elapsed >= 60
      ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`
      : `${elapsed}s`

  return (
    <div className={`flex flex-col items-center justify-center text-center ${compact ? 'py-8' : 'py-16'}`}>
      <div
        className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200"
        style={{ borderTopColor: NAVY }}
      />
      <div className="mt-4 h-1.5 w-52 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full w-1/2 animate-pulse rounded-full" style={{ backgroundColor: NAVY }} />
      </div>
      <p className="mt-4 text-sm font-semibold" style={{ color: NAVY }}>{title}</p>
      {steps && steps.length > 0 && (
        <p className="mt-1 text-xs font-medium text-aqua">{steps[stepIdx]}</p>
      )}
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
      <p className="mt-2 text-xs text-slate-400">
        {elapsedText}
        {expected ? ` · ${expected}` : ''}
      </p>
    </div>
  )
}

import { useEffect, useState } from 'react'

// 다운로드 페이지처럼 '진행 중'을 보여주는 대기 화면.
// 끝나는 시점을 알 수 없으므로 가짜 %는 쓰지 않고, 움직이는 표시 + 경과 시간 + 단계 안내로
// "무작정 멈춘 게 아니라 작동 중"임을 알린다.
const NAVY = '#14304A'

export default function LoadingWait({
  title,
  hint,
  steps,
  compact = false,
}: {
  title: string
  hint?: string
  steps?: string[] // 순환 표시할 단계 문구(선택)
  compact?: boolean
}) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])

  const safeSteps = steps && steps.length > 0 ? steps : []
  const stepIdx = safeSteps.length > 0 ? Math.min(safeSteps.length - 1, Math.floor(elapsed / 12)) : 0
  const baseProgress = safeSteps.length > 0 ? (stepIdx / safeSteps.length) * 100 : 18
  const withinStep = safeSteps.length > 0 ? Math.min(1, (elapsed % 12) / 12) : Math.min(1, elapsed / 45)
  const progress = Math.min(
    92,
    Math.round(baseProgress + withinStep * (safeSteps.length > 0 ? 100 / safeSteps.length : 74)),
  )

  return (
    <div className={`flex flex-col items-center justify-center text-center ${compact ? 'py-8' : 'py-16'}`}>
      <div className="h-2 w-full max-w-sm overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{ width: `${progress}%`, backgroundColor: NAVY }}
        />
      </div>
      <p className="mt-4 text-sm font-semibold" style={{ color: NAVY }}>{title}</p>
      {safeSteps.length > 0 && (
        <p className="mt-1 text-xs font-medium text-aqua">{safeSteps[stepIdx]}</p>
      )}
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  )
}

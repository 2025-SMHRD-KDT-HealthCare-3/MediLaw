import { useMemo } from 'react'

// 광고검토 결과를 '관계도(마인드맵)'로 그리는 컴포넌트.
// 가운데 = 입력한 광고 문구(라벨만, 실제 문구는 호버 툴팁), 가지 = 위반 쟁점(위험도색),
// 잎 = 각 쟁점의 근거(판례·법령). 위→아래 리스트보다 한눈에 들어오게 한다.
// 좌표는 % 기준이라 컨테이너 폭에 맞춰 반응형으로 늘어난다(연결선은 SVG).

interface Citation {
  n: number
  label: string
  source_url?: string
}
export interface GraphItem {
  id: string
  title: string
  reason?: string
  status?: string
  citations?: Citation[]
}

const STATUS_COLOR: Record<string, string> = {
  risk: '#D9534F', // 위반 소지
  todo: '#E8A33D', // 확인 필요
  ok: '#13AAA0', // 문제 없음
  na: '#6B7280', // 해당 없음
}
const CENTER_COLOR = '#374151'

const MAX_LEAVES = 3 // 노드가 복잡해지지 않게 쟁점당 근거는 최대 3개만 그린다
const PAD = 18 // 가지 좌우 여백(%)

// k개를 가로로 고르게 분포시킨 x(%) 배열
function spreadX(k: number, pad = PAD): number[] {
  if (k <= 0) return []
  if (k === 1) return [50]
  const span = 100 - 2 * pad
  return Array.from({ length: k }, (_, i) => pad + (span * i) / (k - 1))
}

// 부모(cx) 주변으로 잎 m개를 부채꼴로 분포(가장자리에서 잘리지 않게 clamp)
function leafX(cx: number, m: number): number[] {
  if (m <= 0) return []
  if (m === 1) return [cx]
  const gap = 13
  return Array.from({ length: m }, (_, i) => {
    const x = cx + (i - (m - 1) / 2) * gap
    return Math.max(10, Math.min(90, x))
  })
}

interface PNode {
  key: string
  kind: 'center' | 'finding' | 'leaf'
  x: number
  y: number
  color: string
  label: string
  title?: string
  href?: string
}
interface PEdge {
  key: string
  x1: number
  y1: number
  x2: number
  y2: number
  color: string
  opacity: number
}

export default function AdReviewGraph({
  inputText,
  items,
  centerLabel,
  emptyLabel,
}: {
  inputText: string
  items: GraphItem[]
  centerLabel: string
  emptyLabel: string
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: PNode[] = []
    const edges: PEdge[] = []
    const Y = { topLeaf: 9, topFind: 29, center: 50, botFind: 71, botLeaf: 91 }

    // 중앙: 라벨만 표시(실제 입력문은 길어질 수 있어 호버 툴팁으로만)
    nodes.push({
      key: 'center', kind: 'center', x: 50, y: Y.center,
      color: CENTER_COLOR, label: centerLabel, title: inputText || undefined,
    })

    // 위험 항목이 없으면 가운데 + '문제 없음' 잎 하나
    if (items.length === 0) {
      nodes.push({ key: 'empty', kind: 'leaf', x: 50, y: Y.botFind, color: STATUS_COLOR.ok, label: emptyLabel })
      edges.push({ key: 'e-empty', x1: 50, y1: Y.center, x2: 50, y2: Y.botFind, color: STATUS_COLOR.ok, opacity: 0.5 })
      return { nodes, edges }
    }

    const n = items.length
    const topCount = n === 1 ? 1 : Math.floor(n / 2)
    const top = items.slice(0, topCount)
    const bottom = items.slice(topCount)
    const topXs = spreadX(top.length)
    const botXs = spreadX(bottom.length)

    const place = (item: GraphItem, x: number, findY: number, leafY: number) => {
      const color = STATUS_COLOR[item.status ?? 'na'] ?? STATUS_COLOR.na
      const fkey = `f-${item.id}`
      nodes.push({
        key: fkey, kind: 'finding', x, y: findY, color,
        label: item.title || '-',
        title: [item.title, item.reason].filter(Boolean).join(' — ') || undefined,
      })
      edges.push({ key: `e-${fkey}`, x1: 50, y1: Y.center, x2: x, y2: findY, color, opacity: 0.5 })

      const cits = (item.citations ?? []).slice(0, MAX_LEAVES)
      const lxs = leafX(x, cits.length)
      cits.forEach((c, i) => {
        const lkey = `${fkey}-c${i}`
        nodes.push({
          key: lkey, kind: 'leaf', x: lxs[i], y: leafY, color,
          label: c.label || `[${c.n}]`, title: c.label || undefined, href: c.source_url || undefined,
        })
        edges.push({ key: `e-${lkey}`, x1: x, y1: findY, x2: lxs[i], y2: leafY, color, opacity: 0.3 })
      })
    }

    top.forEach((it, i) => place(it, topXs[i], Y.topFind, Y.topLeaf))
    bottom.forEach((it, i) => place(it, botXs[i], Y.botFind, Y.botLeaf))
    return { nodes, edges }
  }, [items, inputText, centerLabel, emptyLabel])

  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-gray-200 bg-white" style={{ height: 560 }}>
      {/* 연결선 — viewBox 0..100 을 컨테이너에 맞춰 늘리되 선 두께는 일정(non-scaling-stroke) */}
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        {edges.map((e) => (
          <line
            key={e.key}
            x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
            stroke={e.color} strokeOpacity={e.opacity} strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>

      {/* 노드 — % 위치에 절대배치, 중심 기준 정렬 */}
      {nodes.map((nd) => {
        const pos = { left: `${nd.x}%`, top: `${nd.y}%` } as const
        const base = 'absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center shadow-sm'

        if (nd.kind === 'center') {
          return (
            <div key={nd.key} className={`${base} max-w-[190px] rounded-lg px-4 py-2`}
                 style={{ ...pos, backgroundColor: nd.color }} title={nd.title}>
              <span className="block text-sm font-bold text-white">{nd.label}</span>
            </div>
          )
        }

        if (nd.kind === 'finding') {
          return (
            <div key={nd.key} className={`${base} max-w-[150px] rounded-lg px-3 py-2`}
                 style={{ ...pos, backgroundColor: nd.color }} title={nd.title}>
              <span className="line-clamp-2 block text-xs font-semibold leading-snug text-white">{nd.label}</span>
            </div>
          )
        }

        // leaf
        const leafCls = `${base} max-w-[112px] rounded-md px-2.5 py-1`
        const inner = <span className="block truncate text-[11px] font-medium text-white">{nd.label}</span>
        return nd.href ? (
          <a key={nd.key} href={nd.href} target="_blank" rel="noreferrer"
             className={`${leafCls} hover:brightness-110`}
             style={{ ...pos, backgroundColor: nd.color, opacity: 0.92 }} title={nd.title}>
            {inner}
          </a>
        ) : (
          <div key={nd.key} className={leafCls}
               style={{ ...pos, backgroundColor: nd.color, opacity: 0.92 }} title={nd.title}>
            {inner}
          </div>
        )
      })}
    </div>
  )
}

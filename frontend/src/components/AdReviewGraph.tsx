import { useMemo } from 'react'

// 광고검토 결과 '관계도(마인드맵)'.
// 중앙 = 입력한 광고 문구(라벨 + 짧은 스니펫) → 가지 = 위반 쟁점(문구 + 위험등급)
// → 잎 = 각 쟁점의 근거 법령·판례.
// 잎은 가지 근처에 '세로로 쌓아' 이웃 가지의 잎과 겹치지 않게 한다(박스 겹침/글자 가림 방지).

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
  risk: '#D9534F',
  todo: '#E8A33D',
  ok: '#13AAA0',
  na: '#6B7280',
}
const CENTER_COLOR = '#374151'
const PAD = 12

function spreadX(k: number, pad = PAD): number[] {
  if (k <= 0) return []
  if (k === 1) return [50]
  const span = 100 - 2 * pad
  return Array.from({ length: k }, (_, i) => pad + (span * i) / (k - 1))
}

// reason 끝의 "(근거: …)" 에서 법령·판례명을 뽑는다(괄호/대괄호 안 콤마는 보호).
function parseBasis(reason?: string): string[] {
  if (!reason) return []
  const m = reason.match(/\(\s*근거\s*:\s*([\s\S]+?)\)\s*$/)
  if (!m) return []
  const parts: string[] = []
  let depth = 0
  let cur = ''
  for (const ch of m[1]) {
    if (ch === '(' || ch === '[') depth++
    else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1)
    if (ch === ',' && depth === 0) {
      parts.push(cur)
      cur = ''
    } else {
      cur += ch
    }
  }
  if (cur) parts.push(cur)
  const cleaned = parts
    .map((p) =>
      p
        .replace(/^\s*\[[^\]]*\]\s*/, '')
        .replace(/^\s*\([^()]*\)\s*/, '')
        .replace(/\s*\([^()]*\)\s*$/, '')
        .replace(/\.pdf$/i, '')
        .trim(),
    )
    .filter(Boolean)
  return [...new Set(cleaned)]
}

interface PNode {
  key: string
  kind: 'center' | 'finding' | 'leaf'
  x: number
  y: number
  color: string
  label: string
  sub?: string
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
  centerLabel,
  inputSnippet,
  emptyLabel,
  items,
  statusLabels,
}: {
  centerLabel: string
  inputSnippet: string
  emptyLabel: string
  items: GraphItem[]
  statusLabels: Record<string, string>
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: PNode[] = []
    const edges: PEdge[] = []
    // 위쪽 가지의 잎은 가지 위로(작은 y), 아래쪽 가지의 잎은 가지 아래로(큰 y) 세로로 쌓는다.
    const Y = { center: 50, topFind: 29, topLeaf: [15, 4], botFind: 71, botLeaf: [85, 96] }

    const snippet = inputSnippet
      ? `"${inputSnippet.slice(0, 22).trim()}${inputSnippet.length > 22 ? '…' : ''}"`
      : undefined
    nodes.push({ key: 'center', kind: 'center', x: 50, y: Y.center, color: CENTER_COLOR, label: centerLabel, sub: snippet, title: inputSnippet || undefined })

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

    const place = (item: GraphItem, x: number, findY: number, leafYs: number[]) => {
      const color = STATUS_COLOR[item.status ?? 'na'] ?? STATUS_COLOR.na
      const fkey = `f-${item.id}`
      nodes.push({
        key: fkey,
        kind: 'finding',
        x,
        y: findY,
        color,
        label: item.title || '-',
        sub: statusLabels[item.status ?? 'na'],
        title: [item.title, item.reason].filter(Boolean).join(' — ') || undefined,
      })
      edges.push({ key: `e-${fkey}`, x1: 50, y1: Y.center, x2: x, y2: findY, color, opacity: 0.5 })

      // 잎 = 근거: citations 우선, 없으면 reason의 "(근거: …)" 파싱. 최대 2개를 세로로 쌓음.
      const fromCit = (item.citations ?? []).map((c) => ({ label: c.label, href: c.source_url }))
      const basis = fromCit.length > 0 ? fromCit : parseBasis(item.reason).map((label) => ({ label, href: undefined as string | undefined }))
      const leaves = basis.slice(0, leafYs.length)
      leaves.forEach((lf, i) => {
        // 살짝 좌우로 벌리고(겹침 방지 + 가지 느낌) 세로로 분리
        const lx = Math.max(10, Math.min(90, x + (i - (leaves.length - 1) / 2) * 12))
        const ly = leafYs[i]
        const lkey = `${fkey}-b${i}`
        nodes.push({ key: lkey, kind: 'leaf', x: lx, y: ly, color, label: lf.label || '근거', title: lf.label, href: lf.href || undefined })
        edges.push({ key: `e-${lkey}`, x1: x, y1: findY, x2: lx, y2: ly, color, opacity: 0.3 })
      })
    }

    top.forEach((it, i) => place(it, topXs[i], Y.topFind, Y.topLeaf))
    bottom.forEach((it, i) => place(it, botXs[i], Y.botFind, Y.botLeaf))
    return { nodes, edges }
  }, [items, inputSnippet, centerLabel, emptyLabel, statusLabels])

  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-gray-200 bg-white" style={{ height: 720 }}>
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        {edges.map((e) => (
          <line key={e.key} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke={e.color} strokeOpacity={e.opacity} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>

      {nodes.map((nd) => {
        const pos = { left: `${nd.x}%`, top: `${nd.y}%` } as const
        const base = 'absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center shadow-sm'

        if (nd.kind === 'center') {
          return (
            <div key={nd.key} className={`${base} max-w-[260px] rounded-lg px-5 py-3`} style={{ ...pos, backgroundColor: nd.color }} title={nd.title}>
              <span className="block text-sm font-bold text-white">{nd.label}</span>
              {nd.sub && <span className="mt-0.5 block truncate text-[11px] text-white/70">{nd.sub}</span>}
            </div>
          )
        }

        if (nd.kind === 'finding') {
          return (
            <div key={nd.key} className={`${base} max-w-[230px] rounded-lg px-4 py-3`} style={{ ...pos, backgroundColor: nd.color }} title={nd.title}>
              <span className="line-clamp-2 block text-xs font-semibold leading-snug text-white">{nd.label}</span>
              {nd.sub && <span className="mt-0.5 block text-[10px] font-medium text-white/85">{nd.sub}</span>}
            </div>
          )
        }

        const leafCls = `${base} max-w-[210px] rounded-md px-3 py-1.5`
        const inner = <span className="line-clamp-2 block text-[11px] font-medium leading-snug text-white">{nd.label}</span>
        return nd.href ? (
          <a key={nd.key} href={nd.href} target="_blank" rel="noreferrer" className={`${leafCls} hover:brightness-110`} style={{ ...pos, backgroundColor: nd.color, opacity: 0.92 }} title={nd.title}>
            {inner}
          </a>
        ) : (
          <div key={nd.key} className={leafCls} style={{ ...pos, backgroundColor: nd.color, opacity: 0.92 }} title={nd.title}>
            {inner}
          </div>
        )
      })}
    </div>
  )
}

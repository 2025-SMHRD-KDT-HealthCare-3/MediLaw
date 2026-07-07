import { useMemo, useState } from 'react'

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

function spreadX(k: number, pad = 10): number[] {
  if (k <= 0) return []
  if (k === 1) return [50]
  const span = 100 - 2 * pad
  return Array.from({ length: k }, (_, i) => pad + (span * i) / (k - 1))
}

function parseBasis(reason?: string): string[] {
  if (!reason) return []
  const m = reason.match(/\(\s*(?:근거|\uadfc\uac70)\s*:\s*([\s\S]+?)\)\s*$/)
  if (!m) return []

  const parts: string[] = []
  let depth = 0
  let cur = ''
  for (const ch of m[1]) {
    if (ch === '(' || ch === '[') depth += 1
    else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1)

    if (ch === ',' && depth === 0) {
      parts.push(cur)
      cur = ''
    } else {
      cur += ch
    }
  }
  if (cur) parts.push(cur)

  return [...new Set(parts.map((p) => p.trim()).filter(Boolean))]
}

function basisKey(label: string): string {
  const cleaned = label.replace(/\s+/g, ' ').trim()
  const article = cleaned.match(/(.+?제\s*\d+\s*조(?:의\s*\d+)?)/)
  return (article?.[1] ?? cleaned).replace(/\s+/g, '')
}

interface PNode {
  key: string
  kind: 'center' | 'finding' | 'basis'
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

interface BasisEntry {
  label: string
  href?: string
  color: string
  from: { findingKey: string; x: number; y: number; color: string }[]
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
  const [activeFindingKey, setActiveFindingKey] = useState<string | null>(null)

  const { nodes, baseEdges, basisEdges } = useMemo(() => {
    const nodes: PNode[] = []
    const baseEdges: PEdge[] = []
    const basisEdges: PEdge[] = []
    const Y = { center: 50, topFind: 30, botFind: 70 }

    const snippet = inputSnippet
      ? `"${inputSnippet.slice(0, 22).trim()}${inputSnippet.length > 22 ? '...' : ''}"`
      : undefined

    nodes.push({
      key: 'center',
      kind: 'center',
      x: 50,
      y: Y.center,
      color: CENTER_COLOR,
      label: centerLabel,
      sub: snippet,
      title: inputSnippet || undefined,
    })

    if (items.length === 0) {
      nodes.push({ key: 'empty', kind: 'basis', x: 50, y: 72, color: STATUS_COLOR.ok, label: emptyLabel })
      baseEdges.push({ key: 'e-empty', x1: 50, y1: Y.center, x2: 50, y2: 72, color: STATUS_COLOR.ok, opacity: 0.5 })
      return { nodes, baseEdges, basisEdges }
    }

    const topCount = items.length === 1 ? 1 : Math.ceil(items.length / 2)
    const top = items.slice(0, topCount)
    const bottom = items.slice(topCount)
    const topXs = spreadX(top.length, 12)
    const botXs = spreadX(bottom.length, 12)
    const basisMap = new Map<string, BasisEntry>()

    const addFinding = (item: GraphItem, x: number, y: number) => {
      const color = STATUS_COLOR[item.status ?? 'na'] ?? STATUS_COLOR.na
      const fkey = `f-${item.id}`

      nodes.push({
        key: fkey,
        kind: 'finding',
        x,
        y,
        color,
        label: item.title || '-',
        sub: statusLabels[item.status ?? 'na'],
        title: [item.title, item.reason].filter(Boolean).join(' - ') || undefined,
      })
      baseEdges.push({ key: `e-${fkey}`, x1: 50, y1: Y.center, x2: x, y2: y, color, opacity: 0.5 })

      const citations = (item.citations ?? []).map((c) => ({ label: c.label, href: c.source_url }))
      const basis = citations.length > 0
        ? citations
        : parseBasis(item.reason).map((label) => ({ label, href: undefined as string | undefined }))

      basis.forEach((b) => {
        const label = b.label || '근거'
        const key = basisKey(label)
        const existing = basisMap.get(key)
        if (existing) {
          existing.from.push({ findingKey: fkey, x, y, color })
          return
        }
        basisMap.set(key, { label, href: b.href, color, from: [{ findingKey: fkey, x, y, color }] })
      })
    }

    top.forEach((it, i) => addFinding(it, topXs[i], Y.topFind))
    bottom.forEach((it, i) => addFinding(it, botXs[i], Y.botFind))

    const groupedBasis = Array.from(basisMap.values()).slice(0, 6)
    const basisXs = spreadX(groupedBasis.length, 8)
    groupedBasis.forEach((basis, i) => {
      const x = basisXs[i]
      const y = i % 2 === 0 ? 9 : 91
      const key = `basis-${i}`
      const connectedFindings = new Set(basis.from.map((f) => f.findingKey))

      nodes.push({
        key,
        kind: 'basis',
        x,
        y,
        color: basis.color,
        label: basis.label,
        sub: `${connectedFindings.size}개 항목 연결`,
        title: basis.label,
        href: basis.href,
      })

      basis.from.forEach((from, j) => {
        basisEdges.push({
          key: `e-${from.findingKey}-${key}-${j}`,
          x1: from.x,
          y1: from.y,
          x2: x,
          y2: y,
          color: from.color,
          opacity: 0.36,
        })
      })
    })

    return { nodes, baseEdges, basisEdges }
  }, [items, inputSnippet, centerLabel, emptyLabel, statusLabels])

  const visibleBasisEdges = activeFindingKey
    ? basisEdges.filter((e) => e.key.startsWith(`e-${activeFindingKey}-`))
    : []

  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-gray-200 bg-white" style={{ height: 760 }}>
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        {baseEdges.map((e) => (
          <line key={e.key} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke={e.color} strokeOpacity={e.opacity} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        ))}
        {visibleBasisEdges.map((e) => (
          <line key={e.key} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke={e.color} strokeOpacity={e.opacity} strokeWidth={1.8} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>

      {nodes.map((nd) => {
        const pos = { left: `${nd.x}%`, top: `${nd.y}%` } as const
        const isActive = nd.key === activeFindingKey
        const base = `absolute -translate-x-1/2 -translate-y-1/2 text-center shadow-sm transition-transform duration-150 hover:z-30 hover:scale-[1.03] ${isActive ? 'z-30 scale-[1.03] ring-4 ring-black/10' : 'z-10'}`

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
            <button
              key={nd.key}
              type="button"
              className={`${base} max-w-[230px] cursor-pointer rounded-lg px-4 py-3`}
              style={{ ...pos, backgroundColor: nd.color }}
              title={nd.title}
              onClick={() => setActiveFindingKey((prev) => (prev === nd.key ? null : nd.key))}
            >
              <span className="line-clamp-2 block text-xs font-semibold leading-snug text-white">{nd.label}</span>
              {nd.sub && <span className="mt-0.5 block text-[10px] font-medium text-white/85">{nd.sub}</span>}
            </button>
          )
        }

        const cls = `${base} max-w-[260px] rounded-md px-4 py-2.5`
        const inner = (
          <>
            <span className="line-clamp-2 block text-[11px] font-semibold leading-snug text-white">{nd.label}</span>
            {nd.sub && <span className="mt-1 block text-[10px] text-white/80">{nd.sub}</span>}
          </>
        )

        return nd.href ? (
          <a key={nd.key} href={nd.href} target="_blank" rel="noreferrer" className={`${cls} hover:brightness-110`} style={{ ...pos, backgroundColor: nd.color, opacity: 0.94 }} title={nd.title}>
            {inner}
          </a>
        ) : (
          <div key={nd.key} className={cls} style={{ ...pos, backgroundColor: nd.color, opacity: 0.94 }} title={nd.title}>
            {inner}
          </div>
        )
      })}
    </div>
  )
}

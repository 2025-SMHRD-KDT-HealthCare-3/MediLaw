// 체크리스트 = product 백엔드의 '대화 요약(tb_summary)'에 저장/조회한다.
// (예전엔 RAG(/api/rag/chat/checklist)를 화면 진입마다 직접 호출해 매번 새로 생성 → 저장 안 됨.
//  지금은 product가 생성+저장까지 하므로 front는 product API만 쓴다.)
import { api } from './client'
import type { ChecklistItem, ChecklistSummary } from '../types/checklist'

// tb_summary 한 행 (product SummaryResponse)
export interface SummaryRecord {
  summary_id: number
  room_id: number
  admin_id: number
  summary: string | null // {checklist_summary, search_queries, citation_check} JSON 문자열
  checklist_item: string | null // ChecklistItem[] JSON 문자열
  summary_file: string | null
  is_confirmed: boolean
  created_at: string
}

// 화면 렌더용으로 파싱한 형태
export interface ChecklistView {
  checklist: ChecklistItem[]
  summary: ChecklistSummary
}

// 방의 저장된 체크리스트 목록(최신순) 조회 — 모든 로그인 사용자 가능(GET)
export async function getRoomSummaries(roomId: number | string): Promise<SummaryRecord[]> {
  const res = await api.get(`/rooms/${roomId}/summaries`)
  return res.data?.data ?? []
}

// 체크리스트 생성 + 즉시 저장 — 서버가 방 대화이력으로 생성해 tb_summary에 저장하고 그 행을 돌려준다.
// (이미 미확정 요약이 있으면 서버가 재생성 없이 기존 것을 반환 → 중복/재생성 방지)
export async function createRoomSummary(roomId: number | string): Promise<SummaryRecord> {
  const res = await api.post(`/rooms/${roomId}/summaries`, {})
  return res.data?.data
}

// 저장 레코드(JSON 문자열들) → 화면용 체크리스트로 파싱
export function parseSummary(rec: SummaryRecord): ChecklistView {
  let checklist: ChecklistItem[] = []
  try {
    const arr = JSON.parse(rec.checklist_item ?? '[]')
    if (Array.isArray(arr)) checklist = arr
  } catch {
    checklist = []
  }

  let summary: ChecklistSummary = { total: 0, todo: 0, ok: 0, risk: 0, na: 0 }
  try {
    const meta = JSON.parse(rec.summary ?? '{}')
    if (meta?.checklist_summary?.total != null) summary = meta.checklist_summary
  } catch {
    /* meta 파싱 실패 → 아래에서 항목 배열로 직접 집계 */
  }

  // checklist_summary가 없거나 비어 있으면 항목 status로 직접 집계
  if (summary.total === 0 && checklist.length > 0) {
    const s: ChecklistSummary = { total: checklist.length, todo: 0, ok: 0, risk: 0, na: 0 }
    for (const it of checklist) {
      const k = (['todo', 'ok', 'risk', 'na'] as const).find((x) => x === it.status) ?? 'todo'
      s[k] += 1
    }
    summary = s
  }

  return { checklist, summary }
}

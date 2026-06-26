// POST /chat/checklist 200 응답 구조

export type ChecklistStatus = 'todo' | 'ok' | 'risk' | 'na'

export interface Citation {
  n: number
  label: string
  source_type: string   // 'statute' 등
  source_id: number
  snippet: string
  source_url: string
  trust_grade: string
  label_en: string
  snippet_en: string
  is_official_en: boolean
}

export interface ChecklistItem {
  id: string
  title: string
  reason: string
  status: ChecklistStatus
  change: string          // 'added' 등
  segment_index: number
  citations: Citation[]
  note: string
}

export interface ChecklistSummary {
  total: number
  todo: number
  ok: number
  risk: number
  na: number
}

export interface CitationCheckOutput {
  raw: string
  type: string
  exists: boolean
  clause_accurate: boolean
  valid_as_of: boolean
  verified: boolean
  trust_score: number
  status: string          // '확인' | '주의' | '오류'
  matched_label: string
  matched_source_url: string
  note: string
}

export interface CitationCheckSummary {
  total: number
  verified: number
  failed: number
  avg_score: number
  worst_status: string
  min_score: number
}

export interface ChecklistResponse {
  checklist: ChecklistItem[]
  checklist_summary: ChecklistSummary
  sources: Citation[]
  search_queries: string[]
  citation_check: {
    output: CitationCheckOutput[]
    summary: CitationCheckSummary
    as_of: string
  }
  method: string
  lang: string
  as_of: string
}

// 요청 형식
export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}
export interface ChecklistRequest {
  history: ChatTurn[]
  max_topics?: number
  lang?: string
}
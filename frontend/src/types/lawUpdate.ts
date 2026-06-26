export interface LawRevision {
  mst: string
  effective_on: string | null
  promulgated_on: string | null
  promulgation_no: string
  revision_type: string   // '일부개정' | '타법개정' | '제정' 등
  status: string          // '현행' | '시행예정'
  reason: string          // 개정 사유 (빈 문자열일 수 있음)
  detail_url: string
}

export interface LawItem {
  law_id: string
  name: string
  ministry: string
  current: LawRevision | null
  upcoming: LawRevision[]
  history_count: number
  latest_effective_on: string | null
}

export interface LawRevisionsResponse {
  laws: LawItem[]
  tracked: number
  synced_at: string | null
  source: string
}
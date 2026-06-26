import axios from 'axios'
import type { LawRevisionsResponse } from '../types/lawUpdate'

// 노드 브릿지가 /api/rag/* → rag:8000 으로 라우팅
export async function fetchLawRevisions(): Promise<LawRevisionsResponse> {
  const res = await axios.get<LawRevisionsResponse>('/api/rag/v1/laws/revisions')
  return res.data
}
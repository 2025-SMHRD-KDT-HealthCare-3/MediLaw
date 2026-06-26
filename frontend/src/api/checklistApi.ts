import axios from 'axios'
import type { ChecklistRequest, ChecklistResponse } from '../types/checklist'

export async function generateChecklist(req: ChecklistRequest): Promise<ChecklistResponse> {
  const res = await axios.post<ChecklistResponse>('/api/rag/chat/checklist', req)
  return res.data
}
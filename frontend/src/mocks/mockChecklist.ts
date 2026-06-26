import type { ChecklistResponse } from '../types/checklist'

export const mockChecklist: ChecklistResponse = {
  checklist: [
    {
      id: 'ck-1',
      title: '의료광고 사전심의 대상 여부 확인',
      reason: "'국내 최초'·'최고' 등 객관적 근거 없는 표현은 사전심의 및 의료법 제56조 위반 소지가 있습니다.",
      status: 'risk',
      change: 'added',
      segment_index: 0,
      citations: [
        { n: 1, label: '의료법 제56조', source_type: 'statute', source_id: 1, snippet: '', source_url: 'https://www.law.go.kr', trust_grade: 'A', label_en: '', snippet_en: '', is_official_en: false },
      ],
      note: '',
    },
    {
      id: 'ck-2',
      title: '환자 치료 전후 사진 게시 시 동의 절차 확인',
      reason: '환자 사진을 게시하려면 사전에 명시적 동의를 받아야 합니다.',
      status: 'todo',
      change: 'added',
      segment_index: 1,
      citations: [
        { n: 2, label: '의료법 시행령 제23조', source_type: 'statute', source_id: 2, snippet: '', source_url: 'https://www.law.go.kr', trust_grade: 'A', label_en: '', snippet_en: '', is_official_en: false },
      ],
      note: '',
    },
    {
      id: 'ck-3',
      title: '민감정보(건강정보) 별도 동의 절차 마련',
      reason: '건강정보는 민감정보로 분류되어 별도 동의 없이는 처리할 수 없습니다.',
      status: 'todo',
      change: 'added',
      segment_index: 1,
      citations: [
        { n: 3, label: '개인정보보호법 제23조', source_type: 'statute', source_id: 3, snippet: '', source_url: 'https://www.law.go.kr', trust_grade: 'A', label_en: '', snippet_en: '', is_official_en: false },
      ],
      note: '',
    },
    {
      id: 'ck-4',
      title: '의료데이터 보관·파기 기준 수립',
      reason: '보건의료데이터 활용 가이드라인에 따른 보관·파기 기준이 필요합니다.',
      status: 'na',
      change: 'added',
      segment_index: 2,
      citations: [],
      note: '대화에서 직접 다루지 않음',
    },
  ],
  checklist_summary: { total: 4, todo: 2, ok: 0, risk: 1, na: 1 },
  sources: [],
  search_queries: ['의료광고 사전심의', '환자 사진 동의', '건강정보 민감정보'],
  citation_check: {
    output: [],
    summary: { total: 3, verified: 3, failed: 0, avg_score: 91, worst_status: '주의', min_score: 78 },
    as_of: '2026-07',
  },
  method: 'hybrid',
  lang: 'ko',
  as_of: '2026-07',
}
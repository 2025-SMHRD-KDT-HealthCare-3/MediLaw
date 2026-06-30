import { useState } from 'react'
import { reviewAdCopy } from '../api/chat'
import { useLang } from '../i18n/LanguageContext'

interface Citation {
  n: number
  label: string
  snippet?: string
  source_url?: string
  trust_grade?: string
}
interface ChecklistItem {
  id: string
  title: string
  reason?: string
  status?: string
  citations?: Citation[]
}
interface ParsedResult {
  inputText: string
  revision?: string
  checklist: ChecklistItem[]
  summary?: { total: number; todo: number; ok: number; risk: number; na: number }
}

// status → 색 + 라벨 번역키 (라벨은 렌더 시 t()로 변환)
const ITEM_STYLE: Record<string, { labelKey: string; color: string }> = {
  todo: { labelKey: 'ad.statusTodo', color: '#E8A33D' },
  risk: { labelKey: 'ad.statusRisk', color: '#D9534F' },
  ok: { labelKey: 'ad.statusOk', color: '#13AAA0' },
  na: { labelKey: 'ad.statusNa', color: '#6B7280' },
}

// 위험도(high/medium/low) → 화면 상태값 매핑
const RISK_MAP: Record<string, string> = { high: 'risk', medium: 'todo', low: 'ok' }

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB (백엔드 제한)

export default function AdReview() {
  const { lang, t } = useLang()
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ParsedResult | null>(null)
  const [error, setError] = useState('')

  const handleReview = async () => {
    // 텍스트 또는 파일 중 하나는 있어야 함
    if ((!text.trim() && !file) || loading) return

    // 파일 크기 체크
    if (file && file.size > MAX_FILE_SIZE) {
      setError(t('ad.fileTooLarge'))
      return
    }

    setError('')
    setResult(null)
    setLoading(true)
    try {
      const res = await reviewAdCopy(text, file, lang)
      // 응답 데이터 위치 보정: 검토 결과는 ai_copy 안에 담겨 옴 (없으면 root 그대로)
      const root = res.data ?? res
      const data = root.ai_copy ?? root

      // legal_basis는 문자열로 옴 → 한 번 더 파싱
      let legal: any = {}
      try {
        legal = typeof data.legal_basis === 'string'
          ? JSON.parse(data.legal_basis)
          : (data.legal_basis ?? {})
      } catch {
        legal = {}
      }

      // 위험 항목은 legal.findings에 들어옴 (checklist/checklist_summary는 광고검토에서 비어 있음)
      const findings: any[] = Array.isArray(legal.findings) ? legal.findings : []

      const checklist: ChecklistItem[] = findings.map((f, i) => ({
        id: String(f.segment_index ?? i),
        title: f.segment_text,                  // 위험 문구 원문
        reason: f.issue,                        // 위험 사유 (근거 법령은 문장 끝 "(근거: …)")
        status: RISK_MAP[f.risk_level] ?? 'na', // high→위반소지 / medium→확인필요 / low→문제없음
        citations: f.citations ?? [],           // 비어 올 수 있음
      }))

      const summary = {
        total: checklist.length,
        risk: checklist.filter((c) => c.status === 'risk').length,
        todo: checklist.filter((c) => c.status === 'todo').length,
        ok: checklist.filter((c) => c.status === 'ok').length,
        na: checklist.filter((c) => c.status === 'na').length,
      }

      setResult({
        inputText: data.input_text ?? text,
        revision: data.revision_recomm ?? data.alternative_text,
        checklist,
        summary,
      })
    } catch (err: any) {
      console.error('광고검토 에러:', err)
      setError(err.response?.data?.message ?? err.message ?? t('ad.reviewFailed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F7F8FA] p-8">
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-bold text-navy mb-1">{t('ad.title')}</h1>
        <p className="text-sm text-slate-500 mb-6">
          {t('ad.desc')}
        </p>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('ad.placeholder')}
          rows={4}
          disabled={loading}
          className="w-full rounded-lg border border-gray-300 p-4 text-sm focus:border-aqua focus:outline-none disabled:bg-gray-100"
        />

        {/* PDF 업로드 */}
        <div className="mt-3">
          <label className="mb-1 block text-xs font-medium text-slate-500">
            {t('ad.uploadLabel')}
          </label>
          <div className="flex items-center gap-3">
            <input
              type="file"
              accept="application/pdf,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={loading}
              className="text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-navy file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-navy/90 disabled:opacity-50"
            />
            {file && (
              <button
                type="button"
                onClick={() => setFile(null)}
                disabled={loading}
                className="text-xs text-slate-400 hover:text-red-500"
              >
                {t('ad.fileRemove')}
              </button>
            )}
          </div>
          {file && (
            <p className="mt-1 text-xs text-slate-500">
              {t('ad.fileSelected')}: {file.name} ({(file.size / 1024 / 1024).toFixed(1)}MB)
            </p>
          )}
        </div>

        <button
          onClick={handleReview}
          disabled={loading || (!text.trim() && !file)}
          className="mt-4 rounded-lg bg-navy px-6 py-2.5 text-sm font-medium text-white hover:bg-navy/90 disabled:opacity-50"
        >
          {loading ? t('ad.submitting') : t('ad.submit')}
        </button>

        {error && <p className="mt-4 text-sm text-error">{error}</p>}

        {result && (
          <div className="mt-6 space-y-4">
            {/* 요약 */}
            {result.summary && (
              <div className="flex gap-2 text-xs">
                <span className="rounded-full bg-amber-50 px-3 py-1 text-amber-700">
                  {t('ad.statusTodo')} {result.summary.todo}
                </span>
                <span className="rounded-full bg-red-50 px-3 py-1 text-red-700">
                  {t('ad.statusRisk')} {result.summary.risk}
                </span>
                <span className="rounded-full bg-teal-50 px-3 py-1 text-teal-700">
                  {t('ad.statusOk')} {result.summary.ok}
                </span>
              </div>
            )}

            {/* 검토 항목들 */}
            {result.checklist.length === 0 ? (
              <div className="rounded-xl border border-gray-200 bg-white p-6 text-sm text-slate-500">
                {t('ad.noItems')}
              </div>
            ) : (
              result.checklist.map((item) => {
                const s = ITEM_STYLE[item.status ?? ''] ?? ITEM_STYLE.na
                return (
                  <div key={item.id} className="rounded-xl border border-gray-200 bg-white p-6">
                    <div className="mb-2 flex items-start justify-between gap-3">
                      <p className="text-sm font-semibold text-navy">{item.title}</p>
                      <span
                        className="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium"
                        style={{ color: s.color, backgroundColor: `${s.color}1A` }}
                      >
                        ● {t(s.labelKey)}
                      </span>
                    </div>
                    {item.reason && (
                      <p className="text-sm text-slate-600">{item.reason}</p>
                    )}
                    {item.citations && item.citations.length > 0 && (
                      <div className="mt-3 border-t border-gray-100 pt-3">
                        <p className="mb-1 text-xs font-medium text-slate-400">{t('ad.evidenceLabel')}</p>
                        <ul className="space-y-1">
                          {item.citations.map((c) => (
                            <li key={c.n} className="text-xs text-slate-600">
                              [{c.n}]{' '}
                              {c.source_url ? (
                                <a href={c.source_url} target="_blank" rel="noreferrer"
                                   className="text-brand-blue hover:underline">
                                  {c.label}
                                </a>
                              ) : c.label}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )
              })
            )}

            {/* 수정 추천 */}
            {result.revision && result.revision !== result.inputText && (
              <div className="rounded-xl border border-aqua bg-cyan-50 p-6">
                <p className="mb-1 text-xs font-medium text-slate-500">{t('ad.revisionLabel')}</p>
                <p className="text-sm font-medium text-navy">{result.revision}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
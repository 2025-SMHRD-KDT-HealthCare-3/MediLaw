import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { reviewAdCopy, createRoom, getAdReviews, getAdCopy, deleteAdCopy } from '../api/chat'
import { createRoomSummary } from '../api/checklistApi'
import { useLang } from '../i18n/LanguageContext'
import AdReviewGraph from '../components/AdReviewGraph'
import LoadingWait from '../components/LoadingWait'
import { friendlyError } from '../utils/apiError'

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
  suggestion?: string
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

interface AdHistoryItem {
  ai_copy_id: number
  input_text?: string
  created_at?: string
  status: string // risk | todo | ok
}

// 광고검토 응답(또는 이력 단건)을 화면용 ParsedResult로 변환 (검토/이력 양쪽에서 재사용)
function parseAdCopy(data: any, fallbackText = ''): ParsedResult {
  let legal: any = {}
  try {
    legal = typeof data.legal_basis === 'string' ? JSON.parse(data.legal_basis) : (data.legal_basis ?? {})
  } catch {
    legal = {}
  }
  const findings: any[] = Array.isArray(legal.findings)
    ? legal.findings
    : Array.isArray(data.findings)
      ? data.findings
      : []
  const checklist: ChecklistItem[] = findings.map((f, i) => ({
    id: String(f.segment_index ?? i),
    title: f.segment_text,
    reason: f.issue,
    status: RISK_MAP[f.risk_level] ?? 'na',
    suggestion: f.suggestion,
    citations: f.citations ?? [],
  }))
  const summary = {
    total: checklist.length,
    risk: checklist.filter((c) => c.status === 'risk').length,
    todo: checklist.filter((c) => c.status === 'todo').length,
    ok: checklist.filter((c) => c.status === 'ok').length,
    na: checklist.filter((c) => c.status === 'na').length,
  }
  return {
    inputText: data.input_text ?? fallbackText,
    revision: data.revision_recomm ?? data.alternative_text,
    checklist,
    summary,
  }
}

// 이력 카드 상태 계산 (legal_basis 문자열 → risk/todo/ok)
function calcAdStatus(legalBasisStr?: string): string {
  try {
    const legal = JSON.parse(legalBasisStr ?? '{}')
    const findings = Array.isArray(legal.findings) ? legal.findings : []
    if (findings.some((f: any) => f.risk_level === 'high')) return 'risk'
    if (findings.some((f: any) => f.risk_level === 'medium')) return 'todo'
    return 'ok'
  } catch {
    return 'ok'
  }
}

// 전체 비교에서 문제 문구(빨강)·수정 문구(초록)를 본문 글자에 인라인 하이라이트한다.
function highlightText(text: string, phrases: (string | undefined)[], cls: string) {
  const valid = [...new Set(phrases.filter((p): p is string => !!p && p.trim().length > 1).map((p) => p.trim()))].sort(
    (a, b) => b.length - a.length,
  )
  if (valid.length === 0 || !text) return text
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(${valid.map(esc).join('|')})`, 'g')
  return text.split(re).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className={cls}>
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    ),
  )
}

export default function AdReview() {
  const { lang, t } = useLang()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ParsedResult | null>(null)
  const [error, setError] = useState('')
  const [genLoading, setGenLoading] = useState(false)
  const [view, setView] = useState<'list' | 'graph'>('list')
  const [showDetails, setShowDetails] = useState(false) // 부분별 검토(쟁점·관계도) 펼치기
  const [history, setHistory] = useState<AdHistoryItem[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(true) // 사이드바 접기/펼치기

  // 왼쪽 사이드바: 광고검토 이력(과거 대시보드의 '광고문구 검토 이력')
  const loadHistory = async () => {
    try {
      const res = await getAdReviews()
      const list: AdHistoryItem[] = (res.data ?? []).map((a: any) => ({
        ai_copy_id: a.ai_copy_id,
        input_text: a.input_text,
        created_at: a.created_at,
        status: calcAdStatus(a.legal_basis),
      }))
      setHistory(list)
    } catch (e) {
      console.error('광고검토 이력 로드 실패:', e)
    }
  }

  useEffect(() => {
    loadHistory()
  }, [])

  // 새 검토: 입력/결과 비우기
  const handleNewReview = () => {
    setResult(null)
    setText('')
    setFile(null)
    setError('')
    setView('list')
  }

  // 이력 클릭: 과거 검토 불러오기(빠른 GET이라 별도 대기화면 없음)
  const handleSelectReview = async (id: number) => {
    try {
      setError('')
      const res = await getAdCopy(id)
      const data = res.data ?? res
      setResult(parseAdCopy(data))
      setText('')
      setFile(null)
      setView('list')
    } catch (err: any) {
      console.error('이력 불러오기 실패:', err)
      setError(friendlyError(err, t, 'ad.reviewFailed'))
    }
  }

  const handleDeleteReview = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!window.confirm(t('ad.confirmDeleteReview'))) return
    try {
      await deleteAdCopy(id)
      setHistory((prev) => prev.filter((h) => h.ai_copy_id !== id))
    } catch (err) {
      console.error('이력 삭제 실패:', err)
    }
  }

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
      // 검토 결과는 ai_copy 안에 담겨 옴 (없으면 root 그대로)
      const root = res.data ?? res
      setResult(parseAdCopy(root.ai_copy ?? root, text))
      loadHistory() // 방금 검토를 왼쪽 이력 목록에 반영
    } catch (err: any) {
      console.error('광고검토 에러:', err)
      setError(friendlyError(err, t, 'ad.reviewFailed'))
    } finally {
      setLoading(false)
    }
  }

  // 광고검토 결과(체크리스트)를 저장하고 체크리스트 대시보드로 이동.
  // 화면에 보인 검토 항목을 그대로 저장하므로 HMS 재생성/추가 비용이 없다.
  const handleGenerateChecklist = async () => {
    if (!result || genLoading) return
    try {
      setGenLoading(true)
      setError('')
      // tb_summary는 방(room)에 속해야 하므로, 이 광고검토용 방을 하나 만든다.
      const title = (result.inputText || file?.name || t('ad.title')).slice(0, 50)
      const roomRes = await createRoom(title, t('ad.checklistRoomDesc'))
      const roomId = roomRes?.data?.room_id
      if (!roomId) throw new Error('room create failed')
      // 검토 항목을 체크리스트 저장 형식으로 변환(저장본 파서가 기대하는 필드만 담음)
      const items = result.checklist.map((it) => ({
        id: it.id,
        title: it.title,
        reason: it.reason ?? '',
        status: it.status ?? 'na',
        citations: (it.citations ?? []).map((c) => ({
          n: c.n,
          label: c.label,
          source_url: c.source_url ?? '',
        })),
        note: '',
      }))
      await createRoomSummary(roomId, {
        checklist_item: JSON.stringify(items),
        summary: JSON.stringify({ checklist_summary: result.summary }),
      })
      navigate(`/checklist?roomId=${roomId}`)
    } catch (err: any) {
      console.error('체크리스트 생성 실패:', err)
      setError(friendlyError(err, t, 'ad.checklistFailed'))
    } finally {
      setGenLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-[#F7F8FA]">
      {/* 왼쪽: 광고검토 이력 사이드바 (실제 챗봇식 — 과거 검토 들어가기 / 새 검토) */}
      <aside
        className={`flex shrink-0 flex-col bg-navy transition-all duration-200 ${
          sidebarOpen ? 'w-64' : 'w-0 overflow-hidden'
        }`}
      >
        <div className="p-2">
          <button
            onClick={handleNewReview}
            className="flex w-full items-center gap-2 rounded-lg border border-white/20 px-3 py-2 text-sm font-medium text-white transition hover:bg-white/10"
          >
            <span className="text-base leading-none text-aqua">＋</span>
            <span>{t('ad.newReview')}</span>
          </button>
        </div>
        <div className="px-3 pb-1 pt-1 text-[11px] font-semibold tracking-wide text-white/50">{t('ad.historyTitle')}</div>
        <div className="scroll-navy flex-1 overflow-y-auto overflow-x-hidden px-2 pb-3">
          {history.length === 0 && (
            <p className="px-2 py-4 text-xs text-white/40">{t('ad.noHistory')}</p>
          )}
          {history.map((h) => {
            const color = h.status === 'risk' ? '#D9534F' : h.status === 'todo' ? '#E8A33D' : '#13AAA0'
            return (
              <div
                key={h.ai_copy_id}
                onClick={() => handleSelectReview(h.ai_copy_id)}
                className="group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 transition hover:bg-white/10"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm text-white/90">{h.input_text || t('ad.untitledReview')}</p>
                  <p className="text-[11px] text-white/40">{(h.created_at ?? '').slice(0, 10)}</p>
                </div>
                <div className="ml-1 flex shrink-0 items-center gap-1">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                  <button
                    onClick={(e) => handleDeleteReview(e, h.ai_copy_id)}
                    title={t('ad.deleteReview')}
                    className="rounded px-1 text-sm text-white/40 opacity-0 transition hover:text-red-400 group-hover:opacity-100"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </aside>

      {/* 오른쪽: 검토 입력/결과 */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="mx-auto max-w-5xl">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            title={t('common.toggleSidebar')}
            aria-label={t('common.toggleSidebar')}
            className="mb-3 text-lg leading-none text-slate-400 hover:text-navy"
          >
            ☰
          </button>
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
            {/* 네이티브 <input type="file">는 '파일 선택 / 선택된 파일 없음'을 브라우저 OS
                언어로 그려서 영어 모드에서도 한글이 보인다. 그래서 input은 숨기고(sr-only)
                라벨 버튼과 파일명 표시를 직접 그려 t()로 번역되게 한다. */}
            <label
              className={`shrink-0 rounded-lg bg-navy px-4 py-2 text-sm font-medium text-white hover:bg-navy/90 ${
                loading ? 'pointer-events-none opacity-50' : 'cursor-pointer'
              }`}
            >
              {t('ad.fileChoose')}
              <input
                type="file"
                accept="application/pdf,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                disabled={loading}
                className="sr-only"
              />
            </label>
            <span className="min-w-0 truncate text-sm text-slate-600">
              {file ? file.name : t('ad.fileNone')}
            </span>
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

        {/* 검토 진행 중 — 다운로드 페이지처럼 대기 표시(무작정 멈춘 게 아님을 안내) */}
        {loading && (
          <LoadingWait
            title={t('ad.reviewingTitle')}
            hint={t('ad.reviewingHint')}
            steps={[t('ad.reviewStep1'), t('ad.reviewStep2'), t('ad.reviewStep3')]}
          />
        )}

        {/* 체크리스트 생성 중 — 저장이 끝나면 체크리스트 페이지로 전환됨 */}
        {genLoading && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-white/85 px-6">
            <LoadingWait
              title={t('ad.genChecklistLoading')}
              hint={t('ad.genChecklistHint')}
              steps={[t('ad.genStep1'), t('ad.genStep2')]}
            />
          </div>
        )}

        {result && (
          <div className="mt-6 space-y-4">
            {/* 전체 수정 전후 비교 — 기본으로 바로 표시 */}
            {result.revision && result.revision !== result.inputText ? (
              <div className="rounded-xl border border-aqua bg-white p-6">
                <p className="mb-3 text-sm font-semibold text-navy">{t('ad.compareTitle')}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="max-h-72 overflow-auto rounded-lg border border-red-100 bg-red-50/60 p-3">
                    <p className="mb-1 text-xs font-medium text-red-600">{t('ad.beforeLabel')}</p>
                    <p className="whitespace-pre-wrap text-sm text-slate-700">
                      {highlightText(result.inputText, result.checklist.map((c) => c.title), 'rounded bg-red-200 px-0.5 text-red-900')}
                    </p>
                  </div>
                  <div className="max-h-72 overflow-auto rounded-lg border border-teal-100 bg-teal-50/60 p-3">
                    <p className="mb-1 text-xs font-medium text-teal-700">{t('ad.afterLabel')}</p>
                    <p className="whitespace-pre-wrap text-sm text-slate-700">
                      {highlightText(result.revision ?? '', result.checklist.map((c) => c.suggestion), 'rounded bg-teal-200 px-0.5 text-teal-900')}
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-gray-200 bg-white p-6 text-sm text-slate-500">
                {t('ad.noChange')}
              </div>
            )}

            {/* 부분별 검토(쟁점·관계도)는 버튼으로 펼쳐 보기 */}
            <button
              onClick={() => setShowDetails((v) => !v)}
              className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:bg-gray-50"
            >
              {showDetails ? t('ad.hideDetails') : t('ad.showDetails')}
            </button>

            {showDetails && (
              <>
            {/* 요약 + 보기 전환(목록 / 관계도) */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              {result.summary ? (
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
              ) : (
                <span />
              )}
              <div className="inline-flex rounded-lg border border-gray-200 p-0.5 text-xs">
                <button
                  onClick={() => setView('list')}
                  className={`rounded-md px-3 py-1 font-medium ${view === 'list' ? 'bg-navy text-white' : 'text-slate-500 hover:text-navy'}`}
                >
                  {t('ad.viewList')}
                </button>
                <button
                  onClick={() => setView('graph')}
                  className={`rounded-md px-3 py-1 font-medium ${view === 'graph' ? 'bg-navy text-white' : 'text-slate-500 hover:text-navy'}`}
                >
                  {t('ad.viewGraph')}
                </button>
              </div>
            </div>

            {/* 관계도(마인드맵) 보기 */}
            {view === 'graph' && (
              <>
                <AdReviewGraph
                  centerLabel={t('ad.graphInput')}
                  inputSnippet={result.inputText}
                  emptyLabel={t('ad.statusOk')}
                  items={result.checklist}
                  statusLabels={{
                    risk: t('ad.statusRisk'),
                    todo: t('ad.statusTodo'),
                    ok: t('ad.statusOk'),
                    na: t('ad.statusNa'),
                  }}
                />
                {/* 색상 범례 */}
                <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#D9534F' }} />{t('ad.statusRisk')}</span>
                  <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#E8A33D' }} />{t('ad.statusTodo')}</span>
                  <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#13AAA0' }} />{t('ad.statusOk')}</span>
                </div>
              </>
            )}

            {/* 목록 보기 — 검토 항목들 */}
            {view === 'list' && (result.checklist.length === 0 ? (
              <div className="rounded-xl border border-gray-200 bg-white p-6 text-sm text-slate-500">
                {t('ad.noItems')}
              </div>
            ) : (
              <div className="grid gap-4 xl:grid-cols-2">
              {result.checklist.map((item) => {
                const s = ITEM_STYLE[item.status ?? ''] ?? ITEM_STYLE.na
                return (
                  <div key={item.id} className="rounded-xl border border-gray-200 bg-white p-5">
                    <div className="mb-3 flex items-center justify-end">
                      <span
                        className="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium"
                        style={{ color: s.color, backgroundColor: `${s.color}1A` }}
                      >
                        ● {t(s.labelKey)}
                      </span>
                    </div>
                    {/* 수정 전(위험 원문) / 수정 후(대안 문구)를 한 카드에서 나란히 비교 */}
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-lg border border-red-100 bg-red-50/60 p-3">
                        <p className="mb-1 text-xs font-medium text-red-600">{t('ad.beforeLabel')}</p>
                        <p className="whitespace-pre-wrap text-sm text-slate-700">{item.title}</p>
                      </div>
                      {item.suggestion && item.suggestion.trim() && (
                        <div className="rounded-lg border border-teal-100 bg-teal-50/60 p-3">
                          <p className="mb-1 text-xs font-medium text-teal-700">{t('ad.afterLabel')}</p>
                          <p className="whitespace-pre-wrap text-sm text-slate-700">{item.suggestion}</p>
                        </div>
                      )}
                    </div>
                    {item.reason && (
                      <p className="mt-3 text-sm text-slate-600">{item.reason}</p>
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
              })}
              </div>
            ))}
              </>
            )}

            {/* 검토 결과를 체크리스트로 저장 → 대시보드에서 불러오기 */}
            <button
              onClick={handleGenerateChecklist}
              disabled={genLoading}
              className="w-full rounded-lg border border-navy bg-white px-6 py-2.5 text-sm font-medium text-navy hover:bg-navy hover:text-white disabled:opacity-50"
            >
              {genLoading ? t('ad.genChecklistLoading') : t('ad.genChecklist')}
            </button>
          </div>
        )}
        </div>
      </div>
    </div>
  )
}

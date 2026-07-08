import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import ChatMessage from '../components/chat/ChatMessage'
import { useChatStore } from '../store/chatStore'
import type { ChatMessage as ChatMessageType, Citation, CitationStatus } from '../types/chat'
import { createRoom, askAi, getChats, getRooms, deleteRoom } from '../api/chat'
import { useLang } from '../i18n/LanguageContext'
import LoadingWait from '../components/LoadingWait'
import { friendlyError } from '../utils/apiError'

// 백엔드 검증상태 → 우리 CitationStatus 매핑 (문서 §11)
const STATUS_MAP: Record<string, CitationStatus> = {
  CONFIRMED: 'verified',
  WARNING: 'caution',
  ERROR: 'error',
}

// 근거(evidences)·검증(verifications) → 화면용 citations/trustScore 변환.
// 라이브 응답(handleSend)과 대화 복원(mapChats)에서 동일하게 사용해, 새로고침·방
// 재진입 후에도 근거 법령 카드와 신뢰도 점수가 동일하게 나오도록 한다.
// answerText: 답변 본문. 본문에 실제 인용된 [n]에 해당하는 근거만 카드로 노출한다.
//   ※ n ↔ evidences 매핑 근거: FastAPI가 sources에 n=1부터 배열 순서대로 부여하고
//     (routers/chat.py: enumerate(hits, 1)), Product API가 그 순서 그대로 evidence를
//     저장·반환(persist_hms_sources 순회 / get_list는 created_at·evidence_id 오름차순)
//     하므로, 프론트가 받는 evidences[i]가 곧 [i+1] 인용이다.
function buildCitationData(
  evidences: any[] | undefined,
  verifications: any[] | undefined,
  answerText: string,
): { citations?: Citation[]; trustScore?: number } {
  const verificationList = verifications ?? []
  // 본문에 실제 인용된 [n] 집합 — 카드 필터와 신뢰점수 산정이 같은 집합을 공유해
  // '보이는 카드'와 점수 산정 근거가 절대 어긋나지 않게 한다.
  const citedNos = new Set(
    Array.from(String(answerText ?? '').matchAll(/\[(\d+)\]/g), (m) => Number(m[1])),
  )
  const citations: Citation[] = (evidences ?? []).map((ev: any, index: number) => ({
    id: String(ev.evidence_id),
    no: index + 1, // 원래 인용 번호 [n] — 아래 cited-only 필터 전에 부여해 번호 보존
    lawName: ev.article_no ? `${ev.law_name} ${ev.article_no}` : ev.law_name,
    clause: (ev.core_basis ?? '')
      .replace(/^#.*$/gm, '')
      .replace(/\n{2,}/g, '\n')
      .trim(),
    status: 'verified' as CitationStatus,
    sourceUrl: ev.source_url ?? undefined,
  }))
  // 신뢰점수 = '인용되어 실제로 보이는 카드'들의 검증 점수 평균.
  // 카드의 status/reason과 동일한 인덱스 매칭(verificationList[index] ?? [0] 폴백)을 사용해
  // 점수 산정 대상과 카드 목록이 항상 일치하도록 한다. (기존: 검색된 8건 전체 평균)
  const citedIndexes = citations
    .map((_, index) => index)
    .filter((index) => citedNos.has(index + 1))
  const scores = citedIndexes
    .map((index) => Number((verificationList[index] ?? verificationList[0])?.confidence_score))
    .filter((score) => Number.isFinite(score))
  let trustScore =
    scores.length > 0
      ? Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length)
      : undefined
  const hasLegacyEmptySummaryScore = verificationList.some((item: any) => {
    const score = Number(item?.confidence_score)
    return (
      Number.isFinite(score) &&
      score <= 0 &&
      (item?.law_name === 'citation_check.summary' ||
        String(item?.verification_reason ?? '').includes('Citation summary score'))
    )
  })
  // 레거시 폴백도 '보이는 카드' 기준으로 판정 (카드 없는데 점수만 뜨는 일 방지)
  if (hasLegacyEmptySummaryScore && citedIndexes.length > 0 && (trustScore === undefined || trustScore <= 0)) {
    trustScore = 80
  }

  citations.forEach((citation, index) => {
    const verification = verificationList[index] ?? verificationList[0]
    if (verification?.verification_status && STATUS_MAP[verification.verification_status]) {
      citation.status = STATUS_MAP[verification.verification_status]
    }
    // 검증 사유(verification_reason)도 카드 상세 패널에 노출 (없으면 고정 문구 폴백)
    const reason = String(verification?.verification_reason ?? '').trim()
    if (reason) citation.reason = reason
  })

  if (trustScore !== undefined && citations.length > 0 && trustScore < 60) {
    for (const citation of citations) {
      citation.status = 'error'
    }
  }

  // 본문에 실제 인용된 [n]만 남긴다 (n = evidences 1-based 순번, 위 주석 참고).
  // 검증(status·reason)은 원래 인덱스로 이미 매칭을 끝냈으므로 여기서 걸러도 안전.
  // [n] 토큰이 하나도 없는 답변(거절·범위 밖 등)은 근거 목록 자체를 숨긴다.
  const citedOnly = citations.filter((_, index) => citedNos.has(index + 1))
  return { citations: citedOnly.length > 0 ? citedOnly : undefined, trustScore }
}

interface RoomItem {
  room_id: number
  room_title: string
  created_at?: string
  display: string // 사이드바 표시 제목 (첫 질문 우선, 없으면 room_title)
}

function fmtDate(s?: string) {
  return s ? s.slice(0, 10) : ''
}

export default function Chat() {
  const { messages, addMessage, setMessages } = useChatStore()
  const { lang, t } = useLang()
  const [input, setInput] = useState('')
  const [rooms, setRooms] = useState<RoomItem[]>([])
  const [roomId, setRoomId] = useState<number | null>(null) // null = 아직 안 보낸 새 채팅
  const [loading, setLoading] = useState(false) // AI 답변 대기
  const [switching, setSwitching] = useState(false) // 방 전환(대화 불러오기)
  const [sidebarOpen, setSidebarOpen] = useState(true) // 사이드바 접기/펼치기
  const navigate = useNavigate()

  const mapChats = (
    chats: {
      chat_id: number
      speaker_type: string
      chat_text: string
      chatted_at?: string
      evidences?: any[]
      verifications?: any[]
    }[],
  ): ChatMessageType[] =>
    chats.map((c) => {
      const msg: ChatMessageType = {
        id: String(c.chat_id),
        role: c.speaker_type === 'USER' ? 'user' : 'assistant',
        content: c.chat_text,
        timestamp: c.chatted_at ?? '',
      }
      // AI 답변이면 저장된 근거·검증으로 카드·점수 복원 (라이브 응답과 동일하게).
      if (c.speaker_type !== 'USER') {
        const { citations, trustScore } = buildCitationData(c.evidences, c.verifications, c.chat_text)
        msg.citations = citations
        msg.trustScore = trustScore
      }
      return msg
    })

  const loadRooms = async (): Promise<RoomItem[]> => {
    const res = await getRooms()
    // 표시 제목은 백엔드가 한 번에 내려주는 preview(첫 질문) 우선, 없으면 room_title.
    // (예전엔 방마다 getChats를 호출해 방이 많으면 rate limit 429가 났음 → 단일 호출로 변경)
    const list: RoomItem[] = (res.data ?? []).map(
      (r: { room_id: number; room_title: string; created_at?: string; preview?: string | null }) => ({
        room_id: r.room_id,
        room_title: r.room_title,
        created_at: r.created_at,
        display: (r.preview && r.preview.trim().slice(0, 40)) || r.room_title || '',
      }),
    )
    setRooms(list)
    return list
  }

  const openRoom = async (id: number) => {
    try {
      setSwitching(true)
      setRoomId(id)
      const res = await getChats(id)
      setMessages(mapChats(res.data ?? []))
    } catch (err: any) {
      if (err.response?.status === 401) {
        navigate('/login')
        return
      }
      setMessages([])
    } finally {
      setSwitching(false)
    }
  }

  // 진입: 대화 목록 불러오고 가장 최근 방 열기(없으면 빈 새 채팅)
  useEffect(() => {
    const init = async () => {
      try {
        const list = await loadRooms()
        if (list.length > 0) await openRoom(list[0].room_id)
        else {
          setRoomId(null)
          setMessages([])
        }
      } catch (err: any) {
        if (err.response?.status === 401) navigate('/login')
        else console.error('대화 목록 로드 실패:', err)
      }
    }
    init()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 새 채팅: 빈 상태로 둔다. 첫 메시지를 보낼 때 그 질문을 제목으로 방을 만든다(빈 방 안 쌓임).
  const handleNewChat = () => {
    setRoomId(null)
    setMessages([])
    setInput('')
  }

  const handleSelectRoom = (id: number) => {
    if (id === roomId || loading) return
    openRoom(id)
  }

  const handleDeleteRoom = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!window.confirm(t('chat.confirmDelete'))) return
    // 낙관적 업데이트: 화면에서 먼저 즉시 제거(바로 반영) → 실패하면 되돌리고 알림.
    const prev = rooms
    const rest = rooms.filter((r) => r.room_id !== id)
    setRooms(rest)
    if (id === roomId) {
      if (rest.length > 0) openRoom(rest[0].room_id)
      else handleNewChat()
    }
    try {
      await deleteRoom(id)
    } catch (err) {
      console.error('대화 삭제 실패:', err)
      setRooms(prev) // 복구
      alert(friendlyError(err, t, 'chat.deleteFailed'))
    }
  }

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const question = input
    setInput('')

    // 현재 방이 없으면(새 채팅) 질문을 제목으로 방을 만든다.
    let activeId = roomId
    if (activeId == null) {
      try {
        const res = await createRoom(question.slice(0, 40))
        activeId = res.data?.room_id ?? null
        if (activeId == null) throw new Error('room create failed')
        setRoomId(activeId)
        await loadRooms()
      } catch (err: any) {
        if (err.response?.status === 401) {
          navigate('/login')
          return
        }
        addMessage({
          id: Date.now().toString(),
          role: 'assistant',
          content: friendlyError(err, t, 'chat.answerFailed'),
          timestamp: new Date().toISOString(),
        })
        return
      }
    }

    addMessage({
      id: Date.now().toString(),
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    })
    setLoading(true)

    try {
      const res = await askAi(activeId, question, lang)
      const data = res.data
      const answer = data?.answer_chat
      const { citations, trustScore } = buildCitationData(
        data?.evidences,
        data?.verifications,
        answer?.chat_text ?? '',
      )

      addMessage({
        id: String(answer?.chat_id ?? Date.now()),
        role: 'assistant',
        content: answer?.chat_text ?? t('chat.answerEmpty'),
        timestamp: answer?.chatted_at ?? new Date().toISOString(),
        citations,
        trustScore,
      })
    } catch (err: any) {
      console.error('ai-answer 에러:', err)
      addMessage({
        id: Date.now().toString(),
        role: 'assistant',
        content: friendlyError(err, t, 'chat.answerFailed'),
        timestamp: new Date().toISOString(),
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex bg-[#F7F8FA]" style={{ height: 'calc(100vh - 60px)' }}>
      {/* 사이드바 — 대화 목록 (실제 챗봇처럼 이전 대화 들어가기 / 새 채팅) */}
      <aside
        className={`flex flex-col bg-navy transition-all duration-200 ${
          sidebarOpen ? 'w-64' : 'w-0 overflow-hidden'
        }`}
      >
        <div className="p-2">
          <button
            onClick={handleNewChat}
            className="flex w-full items-center gap-2 rounded-lg border border-white/20 px-3 py-2 text-sm font-medium text-white transition hover:bg-white/10"
          >
            <span className="text-base leading-none text-aqua">＋</span>
            <span>{t('chat.newChat')}</span>
          </button>
        </div>
        <div className="px-3 pb-1 pt-1 text-[11px] font-semibold tracking-wide text-white/50">{t('chat.roomListTitle')}</div>
        <div className="scroll-navy flex-1 overflow-y-auto overflow-x-hidden px-2 pb-3">
          {rooms.length === 0 && (
            <p className="px-2 py-4 text-xs text-white/40">{t('chat.noRooms')}</p>
          )}
          {rooms.map((r) => (
            <div
              key={r.room_id}
              onClick={() => handleSelectRoom(r.room_id)}
              className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 transition ${
                r.room_id === roomId ? 'bg-white/15' : 'hover:bg-white/10'
              }`}
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-white/90">{r.display || t('chat.untitled')}</p>
                <p className="text-[11px] text-white/40">{fmtDate(r.created_at)}</p>
              </div>
              <button
                onClick={(e) => handleDeleteRoom(e, r.room_id)}
                title={t('chat.deleteRoom')}
                className="ml-1 shrink-0 rounded px-1.5 text-sm text-white/40 opacity-0 transition hover:text-red-400 group-hover:opacity-100"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* 메인 — 현재 대화 */}
      <div className="flex flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-gray-200 bg-navy px-6 py-4">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            title={t('common.toggleSidebar')}
            aria-label={t('common.toggleSidebar')}
            className="text-lg leading-none text-white/90 hover:text-aqua"
          >
            ☰
          </button>
          <h1 className="text-lg font-bold text-white">{t('chat.title')}</h1>
        </header>

        <main className="flex-1 overflow-y-auto px-6 py-6">
          <div className="mx-auto max-w-3xl space-y-4">
            {switching ? (
              <LoadingWait compact title={t('common.loading')} />
            ) : (
              <>
                {messages.length === 0 && !loading && (
                  <p className="mt-10 text-center text-sm text-slate-400">{t('chat.empty')}</p>
                )}
                {messages.map((msg) => (
                  <ChatMessage key={msg.id} message={msg} />
                ))}
                {loading && <LoadingWait compact title={t('chat.generating')} hint={t('chat.waitHint')} />}
              </>
            )}
          </div>
        </main>

        <footer className="border-t border-gray-200 bg-white px-6 py-4">
          <div className="mx-auto max-w-3xl">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder={t('chat.placeholder')}
                disabled={loading}
                className="flex-1 rounded-full border border-gray-300 px-4 py-2.5 text-sm focus:border-aqua focus:outline-none disabled:bg-gray-100"
              />
              <button
                onClick={handleSend}
                disabled={loading}
                className="rounded-full bg-navy px-5 py-2.5 text-sm font-medium text-white hover:bg-navy/90 disabled:opacity-50"
              >
                {t('chat.send')}
              </button>
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}

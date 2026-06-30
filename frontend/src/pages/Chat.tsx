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

interface RoomItem {
  room_id: number
  room_title: string
  created_at?: string
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

  const mapChats = (chats: { chat_id: number; speaker_type: string; chat_text: string; chatted_at?: string }[]): ChatMessageType[] =>
    chats.map((c) => ({
      id: String(c.chat_id),
      role: c.speaker_type === 'USER' ? 'user' : 'assistant',
      content: c.chat_text,
      timestamp: c.chatted_at ?? '',
    }))

  const loadRooms = async (): Promise<RoomItem[]> => {
    const res = await getRooms()
    const list: RoomItem[] = (res.data ?? []).map((r: { room_id: number; room_title: string; created_at?: string }) => ({
      room_id: r.room_id,
      room_title: r.room_title,
      created_at: r.created_at,
    }))
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
    try {
      await deleteRoom(id)
      const rest = rooms.filter((r) => r.room_id !== id)
      setRooms(rest)
      if (id === roomId) {
        if (rest.length > 0) openRoom(rest[0].room_id)
        else handleNewChat()
      }
    } catch (err) {
      console.error('대화 삭제 실패:', err)
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
      const evidences = data?.evidences ?? []
      const verifications = data?.verifications ?? []

      const citations: Citation[] = evidences.map((ev: any) => ({
        id: String(ev.evidence_id),
        lawName: ev.article_no ? `${ev.law_name} ${ev.article_no}` : ev.law_name,
        clause: (ev.core_basis ?? '')
          .replace(/^#.*$/gm, '')
          .replace(/\n{2,}/g, '\n')
          .trim(),
        status: 'verified',
        sourceUrl: ev.source_url ?? undefined,
      }))

      const firstV = verifications[0]
      const trustScore = firstV?.confidence_score
      if (firstV?.verification_status && STATUS_MAP[firstV.verification_status] && citations[0]) {
        citations[0].status = STATUS_MAP[firstV.verification_status]
      }

      addMessage({
        id: String(answer?.chat_id ?? Date.now()),
        role: 'assistant',
        content: answer?.chat_text ?? t('chat.answerEmpty'),
        timestamp: answer?.chatted_at ?? new Date().toISOString(),
        citations: citations.length > 0 ? citations : undefined,
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
        className={`flex flex-col border-r border-slate-200 bg-[#EEF2F7] transition-all duration-200 ${
          sidebarOpen ? 'w-64' : 'w-0 overflow-hidden border-r-0'
        }`}
      >
        <div className="p-3">
          <button
            onClick={handleNewChat}
            className="w-full rounded-lg bg-navy px-4 py-2 text-sm font-medium text-white hover:bg-navy/90"
          >
            {t('chat.newChat')}
          </button>
        </div>
        <div className="px-4 pb-1 text-xs font-medium text-slate-400">{t('chat.roomListTitle')}</div>
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {rooms.length === 0 && (
            <p className="px-2 py-4 text-xs text-slate-400">{t('chat.noRooms')}</p>
          )}
          {rooms.map((r) => (
            <div
              key={r.room_id}
              onClick={() => handleSelectRoom(r.room_id)}
              className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 transition ${
                r.room_id === roomId ? 'bg-white shadow-sm' : 'hover:bg-white/60'
              }`}
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-slate-700">{r.room_title || t('chat.untitled')}</p>
                <p className="text-[11px] text-slate-400">{fmtDate(r.created_at)}</p>
              </div>
              <button
                onClick={(e) => handleDeleteRoom(e, r.room_id)}
                title={t('chat.deleteRoom')}
                className="ml-1 shrink-0 rounded px-1.5 text-sm text-slate-300 opacity-0 transition hover:text-red-500 group-hover:opacity-100"
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

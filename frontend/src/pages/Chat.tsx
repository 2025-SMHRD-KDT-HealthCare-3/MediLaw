import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import ChatMessage from '../components/chat/ChatMessage'
import { useChatStore } from '../store/chatStore'
import type { ChatMessage as ChatMessageType, Citation, CitationStatus } from '../types/chat'
import { createRoom, askAi, getChats } from '../api/chat'

// 백엔드 검증상태 → 우리 CitationStatus 매핑 (문서 §11)
const STATUS_MAP: Record<string, CitationStatus> = {
  CONFIRMED: 'verified',
  WARNING: 'caution',
  ERROR: 'error',
}

const ROOM_KEY = 'medilaw_current_room' // localStorage 키

export default function Chat() {
  const { messages, addMessage, setMessages } = useChatStore()
  const [input, setInput] = useState('')
  const [lang, setLang] = useState<'ko' | 'en'>('ko') // 입력 언어 (기본 한국어)
  const [roomId, setRoomId] = useState<number | string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  // 화면 진입: 저장된 방 있으면 이어보기, 없으면 새 방 생성
  useEffect(() => {
    const init = async () => {
      const savedId = localStorage.getItem(ROOM_KEY)

      // 1) 저장된 방이 있으면 그 방 대화 불러오기
      if (savedId) {
        try {
          const res = await getChats(savedId)
          const chats = res.data ?? []
          const restored: ChatMessageType[] = chats.map((c: any) => ({
            id: String(c.chat_id),
            role: c.speaker_type === 'USER' ? 'user' : 'assistant',
            content: c.chat_text,
            timestamp: c.chatted_at,
          }))
          setMessages(restored)
          setRoomId(savedId)
          return
        } catch (err: any) {
          if (err.response?.status === 401) {
            navigate('/login')
            return
          }
          // 방이 사라졌거나 오류 → 저장값 지우고 새로 생성으로 진행
          localStorage.removeItem(ROOM_KEY)
        }
      }

      // 2) 저장된 방 없음 → 새 방 생성
      try {
        const res = await createRoom('의료법 상담')
        const newId = res.data?.room_id ?? null
        setRoomId(newId)
        if (newId != null) localStorage.setItem(ROOM_KEY, String(newId))
        setMessages([])
      } catch (err: any) {
        if (err.response?.status === 401) {
          navigate('/login')
          return
        }
        console.error('createRoom 에러:', err)
      }
    }
    init()
  }, [navigate, setMessages])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    if (!roomId) {
      alert('방이 아직 준비되지 않았어요. 잠시 후 다시 시도해주세요.')
      return
    }

    const question = input
    addMessage({
      id: Date.now().toString(),
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    })
    setInput('')
    setLoading(true)

    try {
      const res = await askAi(roomId, question, lang)
      const data = res.data
      const answer = data?.answer_chat
      const evidences = data?.evidences ?? []
      const verifications = data?.verifications ?? []

      // 근거(evidences) → Citation 매핑 (문서 §11)
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

      // 검증(verifications) → 신뢰점수 + 상태 (문서 §11)
      const firstV = verifications[0]
      const trustScore = firstV?.confidence_score
      if (firstV?.verification_status && STATUS_MAP[firstV.verification_status] && citations[0]) {
        citations[0].status = STATUS_MAP[firstV.verification_status]
      }

      const aiMessage: ChatMessageType = {
        id: String(answer?.chat_id ?? Date.now()),
        role: 'assistant',
        content: answer?.chat_text ?? '(답변 내용 없음)',
        timestamp: answer?.chatted_at ?? new Date().toISOString(),
        citations: citations.length > 0 ? citations : undefined,
        trustScore,
      }
      addMessage(aiMessage)
    } catch (err: any) {
      // AI 실패(502 등) 처리 (문서 §9)
      console.error('ai-answer 에러:', err)
      addMessage({
        id: Date.now().toString(),
        role: 'assistant',
        content: '답변을 가져오지 못했어요. (' + (err.response?.data?.message ?? err.message) + ')',
        timestamp: new Date().toISOString(),
      })
    } finally {
      setLoading(false)
    }
  }

  // 새 상담 시작 (현재 방 버리고 새로 생성)
  const handleNewChat = async () => {
    localStorage.removeItem(ROOM_KEY)
    setMessages([])
    setRoomId(null)
    try {
      const res = await createRoom('의료법 상담')
      const newId = res.data?.room_id ?? null
      setRoomId(newId)
      if (newId != null) localStorage.setItem(ROOM_KEY, String(newId))
    } catch (err) {
      console.error('새 상담 생성 에러:', err)
    }
  }

  return (
    <div className="flex flex-col bg-[#F7F8FA]" style={{ height: 'calc(100vh - 60px)' }}>
      <header className="flex items-center justify-between border-b border-gray-200 bg-navy px-6 py-4">
        <div>
          <h1 className="text-lg font-bold text-white">AI 의료법 질의응답</h1>
          <p className="text-xs text-aqua">답이 아니라 상태를 관리하는 도구</p>
        </div>
        <button
          onClick={handleNewChat}
          className="rounded-full border border-aqua px-4 py-1.5 text-sm font-medium text-aqua hover:bg-aqua hover:text-navy"
        >
          + 새 상담
        </button>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.length === 0 && !loading && (
            <p className="text-center text-sm text-slate-400 mt-10">
              의료법 관련 질문을 입력해 상담을 시작하세요.
            </p>
          )}
          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}
          {loading && <p className="text-sm text-slate-400">답변 생성 중…</p>}
        </div>
      </main>

      <footer className="border-t border-gray-200 bg-white px-6 py-4">
        <div className="mx-auto max-w-3xl">
          {/* 입력 언어 토글 */}
          <div className="mb-2 flex items-center gap-3">
            <div className="inline-flex overflow-hidden rounded-lg border border-gray-300">
              <button
                type="button"
                onClick={() => setLang('ko')}
                disabled={loading}
                className={`px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                  lang === 'ko' ? 'bg-navy text-white' : 'bg-white text-slate-500 hover:bg-gray-50'
                }`}
              >
                한국어
              </button>
              <button
                type="button"
                onClick={() => setLang('en')}
                disabled={loading}
                className={`px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                  lang === 'en' ? 'bg-navy text-white' : 'bg-white text-slate-500 hover:bg-gray-50'
                }`}
              >
                English
              </button>
            </div>
            <span className="text-xs text-slate-400">
              영어로 입력하면 한국 법 기준으로 분석해 영어로 답변합니다.
            </span>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder={
                lang === 'en'
                  ? 'Ask a question about Korean medical law…'
                  : '의료법 관련 질문을 입력하세요…'
              }
              disabled={loading}
              className="flex-1 rounded-full border border-gray-300 px-4 py-2.5 text-sm focus:border-aqua focus:outline-none disabled:bg-gray-100"
            />
            <button
              onClick={handleSend}
              disabled={loading}
              className="rounded-full bg-navy px-5 py-2.5 text-sm font-medium text-white hover:bg-navy/90 disabled:opacity-50"
            >
              전송
            </button>
          </div>
        </div>
      </footer>
    </div>
  )
}
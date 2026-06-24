import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import ChatMessage from '../components/chat/ChatMessage'
import { useChatStore } from '../store/chatStore'
import type { ChatMessage as ChatMessageType, Citation, CitationStatus } from '../types/chat'
import { createRoom, askAi } from '../api/chat'

// 백엔드 검증상태 → 우리 CitationStatus 매핑 (문서 §11)
const STATUS_MAP: Record<string, CitationStatus> = {
  CONFIRMED: 'verified',
  WARNING: 'caution',
  ERROR: 'error',
}

export default function Chat() {
  const { messages, addMessage } = useChatStore()
  const [input, setInput] = useState('')
  const [roomId, setRoomId] = useState<number | string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  // 화면 진입 시 방 하나 생성
  useEffect(() => {
    const init = async () => {
      try {
        const res = await createRoom('의료법 상담')
        setRoomId(res.data?.room_id ?? null)
      } catch (err: any) {
        // 로그인 안 된 상태면 로그인 화면으로 (문서 §5)
        if (err.response?.status === 401) {
          navigate('/login')
          return
        }
        console.error('createRoom 에러:', err)
      }
    }
    init()
  }, [navigate])

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
      const res = await askAi(roomId, question)
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

  return (
    <div className="flex h-screen flex-col bg-[#F7F8FA]">
      <header className="border-b border-gray-200 bg-navy px-6 py-4">
        <h1 className="text-lg font-bold text-white">AI 의료법 질의응답</h1>
        <p className="text-xs text-aqua">답이 아니라 상태를 관리하는 도구</p>
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
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="의료법 관련 질문을 입력하세요…"
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
      </footer>
    </div>
  )
}
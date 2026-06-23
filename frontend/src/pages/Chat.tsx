import { useState, useEffect } from 'react'
import ChatMessage from '../components/chat/ChatMessage'
import { useChatStore } from '../store/chatStore'
import type { ChatMessage as ChatMessageType } from '../types/chat'
import { createRoom, askAi } from '../api/chat'

export default function Chat() {
  const { messages, addMessage } = useChatStore()
  const [input, setInput] = useState('')
  const [roomId, setRoomId] = useState<number | string | null>(null)
  const [loading, setLoading] = useState(false)

  // 화면 진입 시 방 하나 생성
  useEffect(() => {
    const init = async () => {
      try {
        const res = await createRoom('의료법 상담')
        console.log('createRoom 응답:', res)
        const id = res.data?.room_id ?? res.data?.room?.room_id ?? res.data?.id
        setRoomId(id)
      } catch (err) {
        console.error('createRoom 에러:', err)
      }
    }
    init()
  }, [])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    if (!roomId) {
      alert('방이 아직 준비되지 않았어요. 잠시 후 다시 시도해주세요.')
      return
    }

    const question = input
    // 1) 내 질문 즉시 표시
    addMessage({
      id: Date.now().toString(),
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    })
    setInput('')
    setLoading(true)

    try {
      // 2) AI 답변 요청
      const res = await askAi(roomId, question)
      console.log('ai-answer 응답:', JSON.stringify(res.data, null, 2))
      const answer = res.data?.answer_chat
      const aiMessage: ChatMessageType = {
        id: String(answer?.chat_id ?? Date.now()),
        role: 'assistant',
        content: answer?.chat_text ?? '(답변 내용 없음)',
        timestamp: new Date().toISOString(),
        // citations / trustScore 는 응답 모양 확인 후 다음 단계에서 매핑
      }
      addMessage(aiMessage)
    } catch (err: any) {
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
          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}
          {loading && (
            <p className="text-sm text-slate-400">답변 생성 중…</p>
          )}
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
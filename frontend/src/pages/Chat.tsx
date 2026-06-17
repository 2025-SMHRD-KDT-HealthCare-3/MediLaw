// src/pages/Chat.tsx
import ChatMessage from '../components/chat/ChatMessage';
import { mockMessages } from '../mocks/mockChat';

export default function Chat() {
  return (
    <div className="flex h-screen flex-col bg-[#F7F8FA]">
      {/* 상단 헤더 */}
      <header className="border-b border-gray-200 bg-navy px-6 py-4">
        <h1 className="text-lg font-bold text-white">AI 의료법 질의응답</h1>
        <p className="text-xs text-aqua">답이 아니라 상태를 관리하는 도구</p>
      </header>

      {/* 메시지 목록 */}
      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {mockMessages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}
        </div>
      </main>

      {/* 하단 입력창 (지금은 UI만, 동작은 백엔드 연결 후) */}
      <footer className="border-t border-gray-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <input
            type="text"
            placeholder="의료법 관련 질문을 입력하세요…"
            className="flex-1 rounded-full border border-gray-300 px-4 py-2.5 text-sm focus:border-aqua focus:outline-none"
          />
          <button className="rounded-full bg-navy px-5 py-2.5 text-sm font-medium text-white hover:bg-navy/90">
            전송
          </button>
        </div>
      </footer>
    </div>
  );
}
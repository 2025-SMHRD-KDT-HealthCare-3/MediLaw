// src/components/RoomDetailModal.tsx
import { useEffect, useState } from 'react';
import { getChats } from '../api/chat';

type Chat = {
  chat_id: number;
  speaker_type: 'USER' | 'AI';
  chat_text: string;
  chatted_at: string;
};

type Props = {
  roomId: number;
  roomTitle: string;
  roomDate: string;
  onClose: () => void;
};

export default function RoomDetailModal({ roomId, roomTitle, roomDate, onClose }: Props) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    getChats(roomId)
      .then((res) => {
        if (!alive) return;
        setChats(res?.data ?? []);
      })
      .catch(() => {
        if (alive) setError('대화 내역을 불러오지 못했어요.');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [roomId]);

  // ESC로 닫기
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const fmtTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleString('ko-KR', {
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(20, 48, 74, 0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '20px',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#fff',
          borderRadius: '16px',
          width: '100%',
          maxWidth: '560px',
          maxHeight: '80vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
        }}
      >
        {/* 헤더 */}
        <div
          style={{
            background: '#14304A',
            color: '#fff',
            padding: '18px 22px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <div style={{ fontSize: '17px', fontWeight: 700 }}>{roomTitle}</div>
            <div style={{ fontSize: '13px', opacity: 0.7, marginTop: '2px' }}>{roomDate}</div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#fff',
              fontSize: '22px',
              cursor: 'pointer',
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* 본문 */}
        <div style={{ padding: '20px 22px', overflowY: 'auto', flex: 1, background: '#F7F8FA' }}>
          {loading && (
            <div style={{ textAlign: 'center', color: '#888', padding: '40px 0' }}>
              불러오는 중...
            </div>
          )}
          {error && (
            <div style={{ textAlign: 'center', color: '#D9534F', padding: '40px 0' }}>{error}</div>
          )}
          {!loading && !error && chats.length === 0 && (
            <div style={{ textAlign: 'center', color: '#888', padding: '40px 0' }}>
              아직 대화 내역이 없어요.
            </div>
          )}

          {!loading &&
            !error &&
            chats.map((c) => {
              const isUser = c.speaker_type === 'USER';
              return (
                <div
                  key={c.chat_id}
                  style={{
                    display: 'flex',
                    justifyContent: isUser ? 'flex-end' : 'flex-start',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ maxWidth: '78%' }}>
                    <div
                      style={{
                        background: isUser ? '#4A90D9' : '#fff',
                        color: isUser ? '#fff' : '#14304A',
                        border: isUser ? 'none' : '1px solid #E2E8F0',
                        padding: '11px 15px',
                        borderRadius: '14px',
                        fontSize: '14px',
                        lineHeight: 1.55,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}
                    >
                      {c.chat_text}
                    </div>
                    <div
                      style={{
                        fontSize: '11px',
                        color: '#aaa',
                        marginTop: '4px',
                        textAlign: isUser ? 'right' : 'left',
                      }}
                    >
                      {fmtTime(c.chatted_at)}
                    </div>
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}
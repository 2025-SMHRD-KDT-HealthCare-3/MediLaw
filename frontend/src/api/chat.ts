// src/api/chat.ts
import { api } from './client';

// 방 생성 → room_id 받기
export async function createRoom(room_title: string, room_desc = '') {
  const res = await api.post('/rooms', { room_title, room_desc });
  return res.data; // { success, message, data: {...} }
}

// AI 답변 요청 (질문 보내면 질문+답변+근거+검증이 같이 옴)
export async function askAi(roomId: number | string, question: string) {
  const res = await api.post(`/rooms/${roomId}/ai-answer`, { question });
  return res.data;
}

// 채팅 이력 조회
export async function getChats(roomId: number | string) {
  const res = await api.get(`/rooms/${roomId}/chats`);
  return res.data;
}

// 내 상담방 목록 조회
export async function getRooms() {
  const res = await api.get('/rooms?skip=0&limit=100');
  return res.data;
}

// 광고문구 검토 이력 조회
export async function getAdReviews() {
  const res = await api.get('/ai-ad-copies');
  return res.data;
}

// 광고문구 검토 요청 (텍스트 + PDF 파일 지원)
// 파일이 있으면 multipart/form-data로 /ai-ad-copies/ad-review 에 전송
export async function reviewAdCopy(text: string, file?: File | null, roomId?: number) {
  const form = new FormData();
  form.append('input_language', 'ko');
  if (text.trim()) form.append('text', text.trim());
  if (file) form.append('file', file); // 필드명 'file'
  if (roomId != null) form.append('room_id', String(roomId));

  const res = await api.post('/ai-ad-copies/ad-review', form);
  return res.data; // { success, message, data: { ai_copy, ... } }
}

// 상담방 삭제
export async function deleteRoom(roomId: number | string) {
  const res = await api.delete(`/rooms/${roomId}`);
  return res.data;
}
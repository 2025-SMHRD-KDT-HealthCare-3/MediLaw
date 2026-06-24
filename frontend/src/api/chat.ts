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

// 광고문구 검토 요청
export async function reviewAdCopy(text: string) {
  const res = await api.post('/ai-ad-copies', { input_text: text });
  return res.data;
}
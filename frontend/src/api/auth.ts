// src/api/auth.ts
import { api } from './client';

// 회원가입
export async function signup(payload: {
  login_id: string;
  password: string;
  name: string;
  email: string;
  phone_number: string;
}) {
  const res = await api.post('/auth/signup', payload);
  return res.data; // { success, message, data } 봉투 그대로
}

// 로그인
export async function login(payload: { login_id: string; password: string }) {
  const res = await api.post('/auth/login', payload);
  return res.data;
}

// 내 정보 조회
export async function getMe() {
  const res = await api.get('/users/me');
  return res.data;
}

// 내 정보 수정
export async function updateMe(payload: {
  name?: string;
  email?: string;
  phone_number?: string;
}) {
  const res = await api.patch('/users/me', payload);
  return res.data;
}

// 로그아웃 (서버 세션 쿠키 삭제)
export async function logout() {
  const res = await api.post('/auth/logout')
  return res.data
}
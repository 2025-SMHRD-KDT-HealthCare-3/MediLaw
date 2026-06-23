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
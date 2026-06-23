// src/api/client.ts
import axios from 'axios';

export const api = axios.create({
  baseURL: '/api',        // ← Vite 프록시가 백엔드로 전달
  withCredentials: true,  // ← 쿠키 인증 같이 보내기 (이거 없으면 로그인 풀림)
});
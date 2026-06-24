// src/api/client.ts
import axios from 'axios';

export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

// 401(인증 만료) 응답이 오면 자동으로 로그인 화면으로
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      // 로그인 깃발 내리기 (persist 저장소도 비움)
      localStorage.removeItem('medilaw-auth');
      // 이미 로그인 페이지가 아니면 이동
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(err);
  }
);
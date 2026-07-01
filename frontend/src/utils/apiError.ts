// 백엔드/프록시 에러를 사용자 친화 문구로 변환한다.
// 원시 메시지("HMS server response timed out", "...서버 응답이 지연..." 등)를 화면에 그대로
// 노출하지 않고, 상황(타임아웃/연결불가/기타)에 맞는 부드러운 안내로 바꾼다.
export function friendlyError(
  err: unknown,
  t: (key: string) => string,
  fallbackKey: string,
): string {
  const e = err as {
    response?: { status?: number; data?: { message?: string; code?: string } }
    code?: string
    message?: string
  }
  const status = e?.response?.status
  const code = (e?.response?.data?.code ?? e?.code ?? '').toUpperCase()
  const raw = (e?.response?.data?.message ?? e?.message ?? '').toLowerCase()

  const isTimeout =
    status === 504 ||
    code.includes('TIMEOUT') ||
    raw.includes('timed out') ||
    raw.includes('timeout') ||
    raw.includes('지연')

  const isUnavailable =
    status === 503 ||
    code.includes('ECONN') ||
    code.includes('UNAVAILABLE') ||
    raw.includes('unavailable') ||
    raw.includes('연결할 수 없')

  if (isTimeout) return t('error.timeout')
  if (isUnavailable) return t('error.unavailable')
  return t(fallbackKey)
}

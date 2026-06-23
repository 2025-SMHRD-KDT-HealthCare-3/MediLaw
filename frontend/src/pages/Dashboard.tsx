import { useEffect, useState } from 'react'
import { getRooms, getAdReviews } from '../api/chat'

interface Room {
  room_id: number
  room_title: string
  room_status?: string
  created_at?: string
}

interface AdReview {
  ai_copy_id: number
  input_text?: string
  result_status?: string
  created_at?: string
}

// 백엔드 안 될 때 보여줄 mock
const MOCK_ROOMS: Room[] = [
  { room_id: 1, room_title: '의료광고 문구 검토 상담', room_status: 'ACTIVE', created_at: '2026-06-20' },
  { room_id: 2, room_title: '비급여 진료비 안내 관련', room_status: 'CLOSED', created_at: '2026-06-18' },
  { room_id: 3, room_title: '환불 규정 문구 확인', room_status: 'ACTIVE', created_at: '2026-06-15' },
]
const MOCK_ADS: AdReview[] = [
  { ai_copy_id: 1, input_text: '100% 안전한 시술, 부작용 없음', result_status: 'ERROR', created_at: '2026-06-20' },
  { ai_copy_id: 2, input_text: '국내 최고 권위의 의료진', result_status: 'WARNING', created_at: '2026-06-19' },
  { ai_copy_id: 3, input_text: '건강검진 패키지 안내', result_status: 'CONFIRMED', created_at: '2026-06-17' },
]

// 상태 → 색상/라벨 (데이터 상태색: teal/amber/red)
const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  ACTIVE: { label: '진행중', color: '#13AAA0' },
  CLOSED: { label: '종료', color: '#6B7280' },
  CONFIRMED: { label: '확인', color: '#13AAA0' },
  WARNING: { label: '주의', color: '#E8A33D' },
  ERROR: { label: '위반 소지', color: '#D9534F' },
}

function StatusBadge({ status }: { status?: string }) {
  const s = STATUS_STYLE[status ?? ''] ?? { label: status ?? '-', color: '#6B7280' }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
      style={{ color: s.color, backgroundColor: `${s.color}1A` }}
    >
      ● {s.label}
    </span>
  )
}

export default function Dashboard() {
  const [rooms, setRooms] = useState<Room[]>([])
  const [ads, setAds] = useState<AdReview[]>([])
  const [usingMock, setUsingMock] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const roomRes = await getRooms()
        const adRes = await getAdReviews()
        const roomList = roomRes.data?.rooms ?? roomRes.data ?? []
        const adList = adRes.data?.ad_copies ?? adRes.data ?? []
        // 데이터가 비어있으면 mock으로
        if (roomList.length === 0 && adList.length === 0) {
          setRooms(MOCK_ROOMS); setAds(MOCK_ADS); setUsingMock(true)
        } else {
          setRooms(roomList); setAds(adList)
        }
      } catch (err) {
        console.error('대시보드 로드 실패, mock 사용:', err)
        setRooms(MOCK_ROOMS); setAds(MOCK_ADS); setUsingMock(true)
      }
    }
    load()
  }, [])

  return (
    <div className="min-h-screen bg-[#F7F8FA] p-8">
      <div className="mx-auto max-w-5xl">
        <h1 className="text-2xl font-bold text-navy mb-1">대시보드</h1>
        <p className="text-sm text-slate-500 mb-8">
          상담 현황과 광고문구 검토 이력을 한눈에 확인하세요.
          {usingMock && <span className="ml-2 text-amber-600">(예시 데이터)</span>}
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 지난 상담방 목록 */}
          <section className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-navy mb-4">지난 상담</h2>
            <div className="space-y-3">
              {rooms.map((r) => (
                <div key={r.room_id} className="flex items-center justify-between border-b border-gray-100 pb-3 last:border-0">
                  <div>
                    <p className="text-sm font-medium text-slate-800">{r.room_title}</p>
                    <p className="text-xs text-slate-400">{r.created_at ?? ''}</p>
                  </div>
                  <StatusBadge status={r.room_status} />
                </div>
              ))}
              {rooms.length === 0 && <p className="text-sm text-slate-400">상담 내역이 없습니다.</p>}
            </div>
          </section>

          {/* 광고문구 검토 이력 */}
          <section className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-navy mb-4">광고문구 검토 이력</h2>
            <div className="space-y-3">
              {ads.map((a) => (
                <div key={a.ai_copy_id} className="flex items-center justify-between border-b border-gray-100 pb-3 last:border-0">
                  <div className="min-w-0 flex-1 pr-3">
                    <p className="truncate text-sm font-medium text-slate-800">"{a.input_text ?? '-'}"</p>
                    <p className="text-xs text-slate-400">{a.created_at ?? ''}</p>
                  </div>
                  <StatusBadge status={a.result_status} />
                </div>
              ))}
              {ads.length === 0 && <p className="text-sm text-slate-400">검토 이력이 없습니다.</p>}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
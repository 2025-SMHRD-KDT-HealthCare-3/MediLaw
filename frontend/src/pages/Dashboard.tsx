import { useEffect, useState } from 'react'
import { getRooms, getAdReviews } from '../api/chat'
import RoomDetailModal from '../components/RoomDetailModal'

interface Room {
  room_id: number
  room_title: string
  room_status?: string
  created_at?: string
}

interface AdReview {
  ai_copy_id: number
  input_text?: string
  created_at?: string
  status: string // 계산된 상태: ok / todo / risk
}

const ROOM_STYLE: Record<string, { label: string; color: string }> = {
  ACTIVE: { label: '진행중', color: '#13AAA0' },
  CLOSED: { label: '종료', color: '#6B7280' },
}
const AD_STYLE: Record<string, { label: string; color: string }> = {
  risk: { label: '위반 소지', color: '#D9534F' },
  todo: { label: '확인 필요', color: '#E8A33D' },
  ok: { label: '문제 없음', color: '#13AAA0' },
}

function fmtDate(s?: string) {
  if (!s) return ''
  return s.slice(0, 10) // 2026-06-23
}

// legal_basis 문자열에서 상태 계산
function calcAdStatus(legalBasisStr?: string): string {
  try {
    const legal = JSON.parse(legalBasisStr ?? '{}')
    const sum = legal.checklist_summary
    if (!sum) return 'ok'
    if (sum.risk > 0) return 'risk'
    if (sum.todo > 0) return 'todo'
    return 'ok'
  } catch {
    return 'ok'
  }
}

export default function Dashboard() {
  const [rooms, setRooms] = useState<Room[]>([])
  const [ads, setAds] = useState<AdReview[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedRoom, setSelectedRoom] = useState<Room | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const roomRes = await getRooms()
        const adRes = await getAdReviews()
        setRooms(roomRes.data ?? [])
        const adList = (adRes.data ?? []).map((a: any) => ({
          ai_copy_id: a.ai_copy_id,
          input_text: a.input_text,
          created_at: a.created_at,
          status: calcAdStatus(a.legal_basis),
        }))
        setAds(adList)
      } catch (err) {
        console.error('대시보드 로드 실패:', err)
      } finally {
        setLoading(false)
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
        </p>

        {loading ? (
          <p className="text-sm text-slate-400">불러오는 중…</p>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* 지난 상담 */}
            <section className="rounded-xl border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-semibold text-navy mb-4">지난 상담</h2>
              <div className="space-y-3">
                {rooms.map((r) => {
                  const s = ROOM_STYLE[r.room_status ?? ''] ?? { label: r.room_status ?? '-', color: '#6B7280' }
                  return (
                    <div
                      key={r.room_id}
                      onClick={() => setSelectedRoom(r)}
                      className="flex cursor-pointer items-center justify-between border-b border-gray-100 pb-3 transition-colors last:border-0 hover:bg-gray-50"
                    >
                      <div>
                        <p className="text-sm font-medium text-slate-800">{r.room_title}</p>
                        <p className="text-xs text-slate-400">{fmtDate(r.created_at)}</p>
                      </div>
                      <span className="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium"
                        style={{ color: s.color, backgroundColor: `${s.color}1A` }}>
                        ● {s.label}
                      </span>
                    </div>
                  )
                })}
                {rooms.length === 0 && <p className="text-sm text-slate-400">상담 내역이 없습니다.</p>}
              </div>
            </section>

            {/* 광고문구 검토 이력 */}
            <section className="rounded-xl border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-semibold text-navy mb-4">광고문구 검토 이력</h2>
              <div className="space-y-3">
                {ads.map((a) => {
                  const s = AD_STYLE[a.status]
                  return (
                    <div key={a.ai_copy_id} className="flex items-center justify-between border-b border-gray-100 pb-3 last:border-0">
                      <div className="min-w-0 flex-1 pr-3">
                        <p className="truncate text-sm font-medium text-slate-800">"{a.input_text ?? '-'}"</p>
                        <p className="text-xs text-slate-400">{fmtDate(a.created_at)}</p>
                      </div>
                      <span className="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium"
                        style={{ color: s.color, backgroundColor: `${s.color}1A` }}>
                        ● {s.label}
                      </span>
                    </div>
                  )
                })}
                {ads.length === 0 && <p className="text-sm text-slate-400">검토 이력이 없습니다.</p>}
              </div>
            </section>
          </div>
        )}
      </div>

      {/* 상담 상세 모달 */}
      {selectedRoom && (
        <RoomDetailModal
          roomId={selectedRoom.room_id}
          roomTitle={selectedRoom.room_title}
          roomDate={fmtDate(selectedRoom.created_at)}
          onClose={() => setSelectedRoom(null)}
        />
      )}
    </div>
  )
}
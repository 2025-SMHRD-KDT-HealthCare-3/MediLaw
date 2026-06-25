import { useEffect, useState } from 'react'
import { getRooms, getAdReviews, deleteRoom } from '../api/chat'
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
// 위험 정보는 legal.findings에 들어옴 (checklist_summary는 광고검토에서 항상 비어 있음)
function calcAdStatus(legalBasisStr?: string): string {
  try {
    const legal = JSON.parse(legalBasisStr ?? '{}')
    const findings = Array.isArray(legal.findings) ? legal.findings : []
    if (findings.some((f: any) => f.risk_level === 'high')) return 'risk'
    if (findings.some((f: any) => f.risk_level === 'medium')) return 'todo'
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
  const [deletingId, setDeletingId] = useState<number | null>(null)

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

  // 상담 삭제
  const handleDelete = async (e: React.MouseEvent, room: Room) => {
    e.stopPropagation() // 카드 클릭(모달 열기) 막기
    if (!window.confirm(`'${room.room_title}' 상담을 삭제할까요?`)) return
    setDeletingId(room.room_id)
    try {
      await deleteRoom(room.room_id)
      setRooms((prev) => prev.filter((r) => r.room_id !== room.room_id))
    } catch (err) {
      console.error('삭제 실패:', err)
      alert('삭제에 실패했어요. 잠시 후 다시 시도해주세요.')
    } finally {
      setDeletingId(null)
    }
  }

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
                      className="group flex cursor-pointer items-center justify-between border-b border-gray-100 pb-3 transition-colors last:border-0 hover:bg-gray-50"
                    >
                      <div>
                        <p className="text-sm font-medium text-slate-800">{r.room_title}</p>
                        <p className="text-xs text-slate-400">{fmtDate(r.created_at)}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium"
                          style={{ color: s.color, backgroundColor: `${s.color}1A` }}>
                          ● {s.label}
                        </span>
                        <button
                          onClick={(e) => handleDelete(e, r)}
                          disabled={deletingId === r.room_id}
                          title="삭제"
                          className="shrink-0 rounded-md px-2 py-1 text-sm text-slate-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 disabled:opacity-50"
                        >
                          ✕
                        </button>
                      </div>
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
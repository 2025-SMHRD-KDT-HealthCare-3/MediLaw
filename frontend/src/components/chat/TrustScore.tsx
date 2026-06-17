// src/components/chat/TrustScore.tsx

interface TrustScoreProps {
  score: number; // 0~100
}

export default function TrustScore({ score }: TrustScoreProps) {
  // 점수 구간별 색/라벨 (상태 색 토큰 재사용)
  const { color, label } =
    score >= 80
      ? { color: 'var(--color-confirmed)', label: '높음' }
      : score >= 60
      ? { color: 'var(--color-warning)', label: '보통' }
      : { color: 'var(--color-error)', label: '낮음' };

  // 원 둘레 = 2πr, 점수만큼만 채우고 나머지는 비움
  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div className="inline-flex items-center gap-2">
      <svg width="44" height="44" viewBox="0 0 44 44" className="-rotate-90">
        {/* 회색 배경 트랙 */}
        <circle cx="22" cy="22" r={radius} fill="none" stroke="#E5E7EB" strokeWidth="4" />
        {/* 점수만큼 채워지는 색 링 */}
        <circle
          cx="22" cy="22" r={radius}
          fill="none" stroke={color} strokeWidth="4" strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
      </svg>
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-bold" style={{ color }}>{score}</span>
        <span className="text-[10px] text-gray-500">신뢰도 {label}</span>
      </div>
    </div>
  );
}
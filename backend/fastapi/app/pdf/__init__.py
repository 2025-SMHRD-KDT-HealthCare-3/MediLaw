"""PDF 처리 파이프라인 (멀티에이전트 계약 기반).

단계: 라우팅(routing) → 추출(extract_digital / extract_ocr) → 세그먼트(segment)
      → 위험판정(review) → 치환(revise). 공유 계약은 schema.py.
"""

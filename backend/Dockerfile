# product 서버 (FastAPI 본체 — 로그인·회원·채팅). 포트 8001.
# 빌드 컨텍스트는 backend/ 이며, .dockerignore 로 node/·fastapi/·node_modules/ 를 제외한다.
FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 설치(레이어 캐시 활용). requirements.txt 만 먼저 복사.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사 (app/, migrations/, alembic.ini 등)
COPY . .

EXPOSE 8001

# 기동: 팀 공용 원격 DB는 스키마가 이미 head(alembic_version=20260615_0002)라 부팅 시
# 마이그레이션은 돌리지 않는다. 바로 로그인 테스트가 되도록 기본 계정(test/test1234)만
# 멱등 시드한 뒤(이미 있으면 생략) uvicorn 을 띄운다. 시드 실패는 무시되고 서버는 계속 뜬다.
# (빈 DB를 새로 쓸 경우엔 컨테이너 안에서 수동으로:  alembic upgrade head)
CMD ["sh", "-c", "python -m app.seed; uvicorn app.main:app --host 0.0.0.0 --port 8001"]

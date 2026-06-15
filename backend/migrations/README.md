# Alembic migrations

Alembic 기본 파일은 포함되어 있습니다. 최초 DB 생성 전 아래 명령으로 리비전을 만들 수 있습니다.

```bash
alembic revision --autogenerate -m "create initial tables"
alembic upgrade head
```

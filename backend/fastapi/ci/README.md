# FastAPI 백엔드 CI (GitHub Actions)

`github-actions-fastapi-tests.yml` 은 `backend/fastapi/**` 를 건드리는 모든
push / pull_request 에서 **결정론 테스트 서브셋**을 실행하는 워크플로다.
시크릿(OPENAI_API_KEY 등)은 전혀 필요 없다.

## 설치 (한 줄)

GitHub은 레포 루트의 `.github/workflows/` 만 인식하므로, 아래 명령으로 복사한다.

```bash
mkdir -p /home/user1/MediLaw/.github/workflows && cp /home/user1/MediLaw/backend/fastapi/ci/github-actions-fastapi-tests.yml /home/user1/MediLaw/.github/workflows/fastapi-tests.yml
```

복사 후 `.github/workflows/fastapi-tests.yml` 을 커밋·푸시하면 활성화된다.

## 무엇을 실행하나

- ubuntu-latest + Python 3.12 (Dockerfile `python:3.12-slim` 과 동일 버전), pip 캐시 사용
- `pip install -r requirements.txt pytest` (pytest 는 requirements.txt 에 없어 별도 설치)
- `backend/fastapi` 를 working-directory 로 `pytest tests/ -q -k "<DB 의존 6건 제외식>"`

## 왜 이 서브셋인가 (전체 59개 기준)

CI 환경에는 두 가지가 없다: **OPENAI_API_KEY** 와 **SQLite DB**(`data/medilaw.db`,
1.1GB, `.gitignore` 의 `data/*.db` 로 git 미포함).

| 구분 | 개수 | CI 에서의 처리 |
|---|---|---|
| 결정론 테스트 (키·DB 불필요) | 47 | 실행 → PASS |
| LLM 통합 테스트 | 6 | 각 테스트가 `os.environ.get("OPENAI_API_KEY")` 부재 시 자체 `pytest.skip` → 자동 SKIP |
| DB 의존 결정론 테스트 | 6 | `-k` 로 명시 제외 (아래 목록) |

`-k` 로 제외하는 6건 (모두 실제 `data/medilaw.db` 의 의료법 조문 데이터가 필요):

- `tests/test_ad_review.py::test_ad_core_statutes_present`
- `tests/test_ad_review.py::test_inject_ad_core_only_for_ad`
- `tests/test_chat_citation.py::test_extract_real_vs_fake_statute`
- `tests/test_chat_citation.py::test_summarize_mixed`
- `tests/test_chat_citation.py::test_paragraph_hallucination`
- `tests/test_chat_citation.py::test_chat_citation_check`

이 6건은 의료법 제27·56·57조의 실제 조문(항 단위 포함)을 조회하므로, 최소
픽스처 DB 로 대체하려면 실데이터 수준의 스키마·내용이 필요해 CI 픽스처로는
과하다. 단순 제외가 가장 안전하다.

`--deselect` 대신 `-k` 를 쓰는 이유: 레포에 `backend/pytest.ini` 가 있어
pytest rootdir 가 `backend/` 로 잡히고, nodeid 가 `fastapi/tests/...` 형태가
되어 실행 위치에 따라 `--deselect` 경로가 어긋난다. `-k` 는 경로 무관.

## .env / DB 부재 처리 검증

- `app/config.py` 의 `load_dotenv()` 는 기본 `override=False` → 실제 환경변수가
  `.env` 보다 우선. CI 에는 `.env` 자체가 없으므로(gitignore) 키는 자연히 빈 값.
- DB 경로는 `app/config.py` 의 `DB_PATH`(기본 `data/medilaw.db`) 단일 창구.
  CI 체크아웃에는 `data/` 에 커밋된 파일이 없어 DB 열기 자체가 실패하는 환경이며,
  로컬에서 `OPENAI_API_KEY= DB_PATH=/nonexistent/ci.db` 로 동일 조건을 재현해
  워크플로의 pytest 명령이 **exit 0 (47 passed, 6 skipped, 6 deselected)** 임을 확인했다.

## 로컬에서 CI 와 동일하게 돌려보기

```bash
cd /home/user1/MediLaw/backend/fastapi
OPENAI_API_KEY= DB_PATH=/nonexistent/ci.db python3 -m pytest tests/ -q \
  -k "not test_ad_core_statutes_present and not test_inject_ad_core_only_for_ad and not test_extract_real_vs_fake_statute and not test_summarize_mixed and not test_paragraph_hallucination and not test_chat_citation_check"
```

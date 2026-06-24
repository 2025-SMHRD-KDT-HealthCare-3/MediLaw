"""SQLite 연결 — 스레드별 커넥션. sqlite-vec 확장 로드 시도(있으면)."""
import sqlite3
import threading

from app.config import DB_PATH

_VEC_LOADED = False  # sqlite-vec 확장 로드 성공 여부(첫 커넥션 기준, 읽기전용·동일 DB라 스레드 불변)
_local = threading.local()  # 스레드별 커넥션 보관


def _load_vec(conn: sqlite3.Connection) -> bool:
    """sqlite-vec 확장 로드. 성공 시 True (벡터 KNN 가능), 실패 시 False(numpy 폴백)."""
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def get_conn() -> sqlite3.Connection:
    global _VEC_LOADED
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    loaded = _load_vec(conn)
    # 첫 커넥션 생성 시점의 로드 결과를 모듈 전역에 기록(이후 vec_loaded()가 반환).
    # 읽기전용·동일 DB라 스레드마다 결과가 같아 전역값으로 충분.
    _VEC_LOADED = loaded
    return conn


def db() -> sqlite3.Connection:
    """현재 스레드 전용 커넥션 반환(없으면 생성·저장). 스레드별 커넥션이라 동시 사용 안전."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = get_conn()
        _local.conn = conn
    return conn


def vec_loaded() -> bool:
    db()  # 커넥션 보장
    return _VEC_LOADED


def has_embeddings() -> bool:
    """chunks 임베딩 테이블이 존재하고 행이 있는지."""
    conn = db()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
    ).fetchone()
    if not row:
        return False
    return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0

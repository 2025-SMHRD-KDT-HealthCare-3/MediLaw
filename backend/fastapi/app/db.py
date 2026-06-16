"""SQLite 연결 — lru_cache 공유 커넥션. sqlite-vec 확장 로드 시도(있으면)."""
import sqlite3
from functools import lru_cache

from app.config import DB_PATH

_VEC_LOADED = False  # sqlite-vec 확장 로드 성공 여부


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
    _VEC_LOADED = _load_vec(conn)
    return conn


@lru_cache(maxsize=1)
def _shared_conn() -> sqlite3.Connection:
    return get_conn()


def db() -> sqlite3.Connection:
    return _shared_conn()


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

"""기동 시 1회 실행되는 멱등 시드.

빈 DB(팀원이 처음 docker compose up)에서도 곧바로 로그인 테스트가 되도록
기본 계정 하나를 만든다. 이미 있으면 아무것도 하지 않는다(여러 번 떠도 안전).

비밀번호 해싱은 app.core.security.get_password_hash 를 그대로 사용하므로
로그인(verify_password)과 정확히 호환된다.
"""
import logging

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import User

logger = logging.getLogger("app.seed")

DEFAULT_LOGIN_ID = "test"
DEFAULT_PASSWORD = "test1234"


def seed() -> None:
    db = SessionLocal()
    try:
        if db.query(User).filter(User.login_id == DEFAULT_LOGIN_ID).first():
            logger.info("seed: 기본 계정 '%s' 이미 존재 — 생략", DEFAULT_LOGIN_ID)
            return
        db.add(
            User(
                login_id=DEFAULT_LOGIN_ID,
                password_hash=get_password_hash(DEFAULT_PASSWORD),
                name="테스트계정",
                role="USER",
            )
        )
        db.commit()
        logger.info("seed: 기본 계정 생성 완료 (%s / %s)", DEFAULT_LOGIN_ID, DEFAULT_PASSWORD)
    except Exception:
        logger.exception("seed 실패(무시하고 서버는 계속 기동)")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()

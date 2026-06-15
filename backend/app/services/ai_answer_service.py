from sqlalchemy.orm import Session

from app.ai.citation_extractor import extract_citations_stub
from app.ai.citation_verifier import verify_citation_stub
from app.ai.llm_client import generate_mock_answer
from app.ai.rag_service import retrieve_sources_stub
from app.models.user import User
from app.repositories import chat_repository, evidence_repository, verification_repository
from app.schemas.chat_schema import ChatCreate
from app.schemas.evidence_schema import EvidenceCreate
from app.schemas.verification_schema import VerificationCreate
from app.services.room_service import ensure_room_open


def create_ai_answer(db: Session, room_id: int, current_user: User, question: str) -> dict:
    """Create user question, mock AI answer, evidence, and verification atomically."""
    ensure_room_open(db, room_id, current_user)
    try:
        user_chat = chat_repository.create(
            db,
            room_id,
            ChatCreate(chatter_id=current_user.user_id, speaker_type="USER", chat_text=question),
        )

        sources = retrieve_sources_stub(question)
        answer_text = generate_mock_answer(question, sources)
        ai_chat = chat_repository.create(
            db,
            room_id,
            ChatCreate(chatter_id=None, speaker_type="AI", chat_text=answer_text),
        )

        citations = extract_citations_stub(answer_text) or sources
        evidences = [
            evidence_repository.create(
                db,
                EvidenceCreate(
                    ans_id=ai_chat.chat_id,
                    law_name=item.get("law_name"),
                    article_no=item.get("article_no"),
                    core_basis=item.get("core_basis"),
                    source_url=item.get("source_url"),
                ),
            )
            for item in citations
        ]

        verifications = []
        for citation in citations:
            verification_result = verify_citation_stub(citation)
            verifications.append(
                verification_repository.create(
                    db,
                    VerificationCreate(
                        ans_id=ai_chat.chat_id,
                        user_id=current_user.user_id,
                        **verification_result,
                    ),
                )
            )

        db.commit()
        for item in [user_chat, ai_chat, *evidences, *verifications]:
            db.refresh(item)
        return {
            "question_chat": user_chat,
            "answer_chat": ai_chat,
            "evidences": evidences,
            "verifications": verifications,
        }
    except Exception:
        db.rollback()
        raise

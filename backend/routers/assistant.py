from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.ai.shelter_agent import answer_question
from backend.database.connection import get_db
from backend.models import User
from backend.models.assistant_history import AssistantSession, AssistantMessage
from backend.schemas.common import InputModel
from backend.utils.permissions import get_current_user

router = APIRouter(prefix="/api/assistant", tags=["AI Assistant"])

class ChatRequest(InputModel):
    question: str = Field(min_length=2, max_length=2000)
    session_id: int | None = Field(default=None, gt=0)

def own_session(db, session_id, user):
    row = db.scalar(select(AssistantSession).where(AssistantSession.id == session_id, AssistantSession.user_id == user.id))
    if row is None:
        # A missing and another user's session are deliberately indistinguishable.
        raise HTTPException(404, 'Conversation not found')
    return row

def session_view(row):
    return {'id': row.id, 'title': row.title, 'created_at': row.created_at, 'updated_at': row.updated_at}

def message_view(row):
    return {'role': row.role, 'content': row.content, 'details': row.details, 'created_at': row.created_at}

@router.get('/sessions')
def sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(AssistantSession).where(AssistantSession.user_id == user.id).order_by(AssistantSession.updated_at.desc(), AssistantSession.id.desc()).limit(100))
    return [session_view(row) for row in rows]

@router.get('/sessions/{session_id}')
def session_history(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = own_session(db, session_id, user)
    messages = db.scalars(select(AssistantMessage).where(AssistantMessage.session_id == row.id).order_by(AssistantMessage.id))
    return {**session_view(row), 'messages': [message_view(item) for item in messages]}

@router.post('/chat')
async def chat(data: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    question = data.question.strip()
    session = own_session(db, data.session_id, user) if data.session_id else None
    prior = []
    if session:
        rows = db.scalars(select(AssistantMessage).where(AssistantMessage.session_id == session.id).order_by(AssistantMessage.id.desc()).limit(8)).all()
        # Never send locally retrieved report/status answers to a model on a
        # later turn. Preserve history for display, but omit those whole pairs
        # from the model context (including their corresponding user question).
        ordered = list(reversed(rows))
        for index in range(0, len(ordered) - 1, 2):
            request, answer = ordered[index:index + 2]
            if (request.role != 'user' or answer.role != 'assistant'
                    or (answer.details or {}).get('mode') in {'local_status', 'local_summary', 'local_help'}):
                continue
            prior.extend([{'role': 'user', 'content': request.content[:2000]},
                          {'role': 'assistant', 'content': answer.content[:2000]}])
    result = await answer_question(db, question, user=user, history=prior)
    if session is None:
        session = AssistantSession(user_id=user.id, title=question[:160])
        db.add(session); db.flush()
    else:
        from datetime import datetime
        session.updated_at = datetime.utcnow()
    db.add(AssistantMessage(session_id=session.id, role='user', content=question))
    db.add(AssistantMessage(session_id=session.id, role='assistant', content=str(result.get('answer', ''))[:12000],
                            details={'mode': result.get('mode'), 'warning': result.get('warning'), 'sources': result.get('sources', [])}))
    db.commit()
    return {**result, 'session_id': session.id}

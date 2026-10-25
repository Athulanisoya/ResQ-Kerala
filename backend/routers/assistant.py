from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session
from backend.ai.shelter_agent import answer_question
from backend.database.connection import get_db
from backend.models import User
from backend.schemas.common import InputModel
from backend.utils.permissions import get_current_user
router = APIRouter(prefix="/api/assistant", tags=["AI Assistant"])
class ChatRequest(InputModel):
    question: str = Field(min_length=2, max_length=2000)
@router.post("/chat")
async def chat(data: ChatRequest,db: Session = Depends(get_db),_user: User = Depends(get_current_user)):
    return await answer_question(db, data.question.strip())
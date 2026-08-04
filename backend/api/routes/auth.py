from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.database import get_db
from models.schemas import AuthRequest, AuthResponse
from services.auth_service import authenticate_with_init_data

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("", response_model=AuthResponse)
async def auth(payload: AuthRequest, db: Session = Depends(get_db)) -> AuthResponse:
    return authenticate_with_init_data(db, payload.initData)
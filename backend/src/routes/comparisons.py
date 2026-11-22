from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.constants.enums import Role
from src.controllers.auth import allow
from src.models.identity import User
from src.models.jobs import Comparison
from src.schemas.requests import ComparisonRequest
from src.services import comparison
from src.utils import views
from src.utils.wakeup import wake

router = APIRouter(prefix='/comparisons')
_ALLOWED = allow(Role.ADMIN, Role.ANALYST)


@router.get('')
def index(db: Session = Depends(connection), actor: User = Depends(_ALLOWED)):
    return [views.comparison(item) for item in
            db.scalars(select(Comparison).order_by(Comparison.id.desc()).limit(100))]


@router.post('', status_code=202)
def create(body: ComparisonRequest, actor: User = Depends(_ALLOWED)):
    item, created = comparison.create(body, actor)
    if created:
        wake()
    return views.comparison(item, detail=True)


@router.get('/{comparison_id}')
def detail(comparison_id: int, db: Session = Depends(connection), actor: User = Depends(_ALLOWED)):
    item = db.get(Comparison, comparison_id)
    if not item:
        raise HTTPException(404, '找不到该对比记录')
    return views.comparison(item, detail=True)

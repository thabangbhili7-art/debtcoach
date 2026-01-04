# app/state_db.py
from __future__ import annotations

from typing import Any, Dict
from sqlalchemy.orm import Session

from .models import ConvoState


def _get_or_create_convo(db: Session, user_id: int) -> ConvoState:
    cs = db.query(ConvoState).filter(ConvoState.user_id == user_id).one_or_none()
    if cs is None:
        cs = ConvoState(user_id=user_id, step="start", scratch={})
        db.add(cs)
        db.commit()
        db.refresh(cs)
    return cs


def get_step(db: Session, user_id: int) -> str:
    cs = _get_or_create_convo(db, user_id)
    return cs.step or "start"


def set_step(db: Session, user_id: int, step: str) -> None:
    cs = _get_or_create_convo(db, user_id)
    cs.step = step
    db.add(cs)
    db.commit()


def get_scratch(db: Session, user_id: int) -> Dict[str, Any]:
    cs = _get_or_create_convo(db, user_id)
    return dict(cs.scratch or {})


def update_scratch(db: Session, user_id: int, **kwargs) -> Dict[str, Any]:
    cs = _get_or_create_convo(db, user_id)
    scratch = dict(cs.scratch or {})
    scratch.update(kwargs)
    cs.scratch = scratch
    db.add(cs)
    db.commit()
    return scratch


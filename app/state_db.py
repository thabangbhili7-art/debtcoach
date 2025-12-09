# app/state_db.py
from sqlalchemy.orm import Session
from typing import Dict, Any, Tuple
from .routes.models import User, ConvoState

def upsert_user(db: Session, phone: str) -> User:
    user = db.query(User).filter(User.phone_e164 == phone).one_or_none()
    if not user:
        user = User(phone_e164=phone)
        db.add(user)
        db.flush()  # get user.id
        # init convo state
        cs = ConvoState(user_id=user.id, step="start", scratch={})
        db.add(cs)
        db.commit()
    return user

def get_state(db: Session, user_id: int) -> Tuple[str, Dict[str, Any]]:
    cs = db.query(ConvoState).filter(ConvoState.user_id == user_id).one()
    return cs.step, dict(cs.scratch or {})

def set_step(db: Session, user_id: int, step: str):
    db.query(ConvoState).filter(ConvoState.user_id == user_id).update({"step": step})
    db.commit()

def update_scratch(db: Session, user_id: int, **kwargs):
    cs = db.query(ConvoState).filter(ConvoState.user_id == user_id).one()
    scratch = dict(cs.scratch or {})
    scratch.update(kwargs)
    cs.scratch = scratch
    db.add(cs)
    db.commit()

# app/state.py
from collections import defaultdict
from typing import Dict, Any

# in-memory store: { user_id: {"step": str, "scratch": {...}} }
STATE: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"step": "start", "scratch": {}})

def get_step(user_id: str) -> str:
    return STATE[user_id]["step"]

def set_step(user_id: str, step: str):
    STATE[user_id]["step"] = step

def get_scratch(user_id: str) -> Dict[str, Any]:
    return STATE[user_id]["scratch"]

def update_scratch(user_id: str, **kwargs):
    STATE[user_id]["scratch"].update(kwargs)

def reset(user_id: str):
    if user_id in STATE:
        STATE[user_id] = {"step": "start", "scratch": {}}

from fastapi import FastAPI
from .routes.whatsapp import router as whatsapp_router
from .db import Base, engine
from . import models 

app = FastAPI(title="DebtCoach API", version="0.0.2")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(whatsapp_router)

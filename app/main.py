from fastapi import FastAPI
from .routes.whatsapp import router as whatsapp_router
from .routes.dashboard import router as dashboard_router

app = FastAPI()

app.include_router(whatsapp_router)
app.include_router(dashboard_router)

@app.get("/health")
def health():
    return {"ok": True}

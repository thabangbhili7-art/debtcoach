from fastapi import FastAPI
from .routes.auth import router as auth_router
from .routes.whatsapp import router as whatsapp_router
from .routes.dashboard import router as dashboard_router
from .routes.admin import router as admin_router



app = FastAPI()

app.include_router(auth_router)
app.include_router(whatsapp_router)
app.include_router(dashboard_router)
app.include_router(admin_router)


@app.get("/health")
def health():
    return {"ok": True}

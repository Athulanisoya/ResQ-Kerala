from fastapi import FastAPI

from backend.database.connection import Base, engine
from backend.models.incident import Incident
from backend.routers.incidents import router as incident_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ResQ Kerala API",
    description="Flood Help Response Managment System",
    version="1.0"
)

app.include_router(incident_router)
@app.get("/")
def home():
    return {
        "message": "ResQ Kerala API is running"
    }
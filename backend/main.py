from fastapi import FastAPI
from backend.database.connection import (Base,engine)
from backend.models.incident import (Incident,IncidentStatusHistory)
from backend.routers.incidents import router as incident_router
Base.metadata.create_all(bind=engine)
app = FastAPI(title="ResQ Kerala API",description="Week 1 Incident Reporting API",version="1.0.0")
app.include_router(incident_router)
@app.get("/")
def home():
    return {"message": "ResQ Kerala API is running"}
@app.get("/health")
def health_check():
    return {"status": "healthy"}
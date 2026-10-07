from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base,sessionmaker
from backend.config import settings

engine=create_engine(settings.DATABASE_URL,echo=True)#for connects python to postgresql
SessionLocal=sessionmaker(autocommit=False,autoflush=False,bind=engine)#create database sessions
Base=declarative_base()
def get_db():
    db =SessionLocal()
    try:
        yield db
    finally:
        db.close()
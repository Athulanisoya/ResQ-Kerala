from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "postgresql+psycopg2://postgres:root@localhost:5432/resq_kerala"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

"""try:
    with engine.connect() as connection:
        print("PostgreSQL connected successfully!")
except Exception as e:
    print("Database connection failed:")
    print(e)
"""

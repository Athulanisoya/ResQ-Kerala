from sqlalchemy import select
from backend.database.connection import SessionLocal
from backend.models.shelter import Shelter
DEMO_SHELTERS = [
    {
        "name": "Demo Community Shelter A",
        "district": "Alappuzha",
        "locality": "Alappuzha",
        "address": "Synthetic demo address A, Alappuzha",
        "capacity": 100,
        "occupied": 35,
        "status": "OPEN",
        "contact": None,
        "source_name": "SYNTHETIC DEMO DATA - NOT AN OFFICIAL SHELTER",
    },
    {
        "name": "Demo Community Shelter B",
        "district": "Alappuzha",
        "locality": "Cherthala",
        "address": "Synthetic demo address B, Cherthala",
        "capacity": 80,
        "occupied": 80,
        "status": "FULL",
        "contact": None,
        "source_name": "SYNTHETIC DEMO DATA - NOT AN OFFICIAL SHELTER",
    },
    {
        "name": "Demo Community Shelter C",
        "district": "Ernakulam",
        "locality": "Aluva",
        "address": "Synthetic demo address C, Aluva",
        "capacity": 60,
        "occupied": 15,
        "status": "OPEN",
        "contact": None,
        "source_name": "SYNTHETIC DEMO DATA - NOT AN OFFICIAL SHELTER",
    },
]
def main():
    with SessionLocal() as db:
        for item in DEMO_SHELTERS:
            existing = db.scalar(select(Shelter).where(
                    Shelter.name == item["name"],
                    Shelter.source_name == item["source_name"],
                )
            )
            if existing:
                continue

            db.add(Shelter(**item))
        db.commit()

    print("Week 3 synthetic demo shelters inserted or already present.")
if __name__ == "__main__":
    main()
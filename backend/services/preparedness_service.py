"""Original source-linked household checklist wording; no dynamic hazard advice."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from backend.models import User
from backend.models.preparedness import PreparednessPlan

REVISION = '2026-11-05.1'
SOURCES = {
 'family': {'title': 'KSDMA family disaster preparedness plan', 'url': 'https://sdma.kerala.gov.in/wp-content/uploads/2018/11/12.Family-Disaster-Prepardness-Plan.pdf'},
 'kit': {'title': 'KSDMA emergency kit · 2020 edition', 'url': 'https://sdma.kerala.gov.in/wp-content/uploads/2020/09/Emergency-Kit-2020-PDF-30092020-1.pdf'},
 'flood': {'title': 'NDMA urban flood precautions', 'url': 'https://ndma.gov.in/en/urban-floods-dos-donts'},
 'landslide': {'title': 'KSDMA landslide precautions', 'url': 'https://sdma.kerala.gov.in/wp-content/uploads/2020/09/Landslide-mathrubhumi-24082020.pdf'},
 'malayalam': {'title': 'KSDMA Malayalam family-plan resource', 'url': 'https://sdma.kerala.gov.in/wp-content/uploads/2020/11/Family-DM-101019-malayalam.pdf'},
}
ITEMS = [
 {'id': 'meeting_points', 'source': 'family', 'en': 'Agree on a nearby and an out-of-area meeting place.', 'ml': 'അടുത്തും പ്രദേശത്തിന് പുറത്തുമായി ഓരോ കൂടിച്ചേരൽ സ്ഥലം തീരുമാനിക്കുക.'},
 {'id': 'contacts', 'source': 'family', 'en': 'Save an emergency contact and share the plan with household members.', 'ml': 'അടിയന്തര ബന്ധപ്പെടൽ വിവരങ്ങൾ സൂക്ഷിച്ച് വീട്ടിലുള്ളവരുമായി പദ്ധതി പങ്കിടുക.'},
 {'id': 'assistance', 'source': 'family', 'en': 'Plan evacuation support for children, older people and anyone needing assistance.', 'ml': 'കുട്ടികൾക്കും വയോധികർക്കും സഹായം ആവശ്യമുള്ളവർക്കും ഒഴിപ്പിക്കൽ സഹായം ആസൂത്രണം ചെയ്യുക.'},
 {'id': 'documents', 'source': 'family', 'en': 'Protect copies of important documents in a portable, water-resistant bag.', 'ml': 'പ്രധാന രേഖകളുടെ പകർപ്പുകൾ കൊണ്ടുപോകാവുന്ന വെള്ളം കടക്കാത്ത ബാഗിൽ സൂക്ഷിക്കുക.'},
 {'id': 'supplies', 'source': 'kit', 'en': 'Pack drinking water, ready-to-eat food, regular medicines and personal hygiene supplies.', 'ml': 'കുടിവെള്ളം, ഉടൻ കഴിക്കാവുന്ന ഭക്ഷണം, പതിവ് മരുന്നുകൾ, ശുചിത്വ സാധനങ്ങൾ എന്നിവ കരുതുക.'},
 {'id': 'devices', 'source': 'kit', 'en': 'Check torch batteries, phone charger or power bank and needed assistive devices.', 'ml': 'ടോർച്ചിന്റെ ബാറ്ററികൾ, ഫോൺ ചാർജർ അല്ലെങ്കിൽ പവർ ബാങ്ക്, ആവശ്യമായ സഹായ ഉപകരണങ്ങൾ എന്നിവ പരിശോധിക്കുക.'},
 {'id': 'flood', 'source': 'flood', 'en': 'Discuss flood evacuation instructions; avoid walking or driving through floodwater.', 'ml': 'വെള്ളപ്പൊക്ക ഒഴിപ്പിക്കൽ നിർദേശങ്ങൾ ചർച്ച ചെയ്യുക; വെള്ളക്കെട്ടിലൂടെ നടക്കുന്നതും വാഹനം ഓടിക്കുന്നതും ഒഴിവാക്കുക.'},
 {'id': 'landslide', 'source': 'landslide', 'en': 'Check official landslide warnings and agree how to act on evacuation instructions.', 'ml': 'ഔദ്യോഗിക ഉരുൾപൊട്ടൽ മുന്നറിയിപ്പുകൾ ശ്രദ്ധിച്ച് ഒഴിപ്പിക്കൽ നിർദേശങ്ങൾ എങ്ങനെ പാലിക്കണമെന്ന് തീരുമാനിക്കുക.'},
]
ITEM_IDS = {item['id'] for item in ITEMS}

class Contact(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=1, max_length=40)
    relationship: str = Field(default='', max_length=80)

class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=0, strict=True)
    guidance_revision: Literal[REVISION]
    language: Literal['en', 'ml'] = 'en'
    completed: list[str] = Field(default_factory=list, max_length=8)
    nearby_meeting: str = Field(default='', max_length=255)
    outside_meeting: str = Field(default='', max_length=255)
    contacts: list[Contact] = Field(default_factory=list, max_length=3)
    support_plan: str = Field(default='', max_length=1500)
    next_review_on: date | None = None
    reviewed: bool = False

    @field_validator('completed')
    @classmethod
    def valid_items(cls, values):
        if set(values)-ITEM_IDS: raise ValueError('Reload the current checklist before saving progress.')
        return sorted(set(values))

def guidance():
    return {'revision': REVISION, 'items': ITEMS, 'sources': SOURCES, 'source_checked_on': '2026-11-05',
            'wording': 'ResQ checklist wording based on the linked resources; not an official translation or location-specific evacuation instruction.'}

def read(db, user):
    row = db.get(PreparednessPlan, user.id)
    if row is None:
        return {'version': 0, 'guidance_revision': REVISION, 'language': 'en', 'completed': [], 'nearby_meeting': '',
                'outside_meeting': '', 'contacts': [], 'support_plan': '', 'next_review_on': None, 'reviewed_at': None,
                'updated_at': None, 'review_due': False, 'guidance_changed': False}
    return {key: getattr(row, key) for key in ('version', 'guidance_revision', 'language', 'completed', 'nearby_meeting',
        'outside_meeting', 'contacts', 'support_plan', 'next_review_on', 'reviewed_at', 'updated_at')} | {
        'review_due': bool(row.next_review_on and row.next_review_on <= datetime.now(timezone(timedelta(hours=5, minutes=30))).date()),
        'guidance_changed': row.guidance_revision != REVISION}

def save(db, user, data):
    actor = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not actor.active: raise HTTPException(403, 'An active account is required.')
    row = db.scalar(select(PreparednessPlan).where(PreparednessPlan.user_id == user.id).execution_options(populate_existing=True))
    if (row.version if row else 0) != data.expected_version: raise HTTPException(409, 'Your plan changed in another tab. Reload before saving.')
    if row is None:
        row = PreparednessPlan(user_id=user.id, version=0); db.add(row)
    values = data.model_dump(exclude={'expected_version', 'reviewed'}, mode='json')
    values['next_review_on'] = data.next_review_on
    for key, value in values.items(): setattr(row, key, value)
    row.version += 1; row.updated_at = datetime.now(timezone.utc)
    row.reviewed_at = row.updated_at if data.reviewed else None
    db.commit()
    return read(db, user)

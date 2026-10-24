"""Idempotent, explicitly demo-gated synthetic bootstrap: python -m app.seed."""
from sqlalchemy import select
from .clock import utc_now
from .companies import FIXTURES, create_company
from .config import settings
from .db import SessionLocal
from .identity import password_hasher
from .models import User, Company

DEMO_PASSWORD='DemoCredit2026!'

def seed_demo(db, *, demo_mode: bool) -> None:
    if not demo_mode: raise RuntimeError('Demo seed is disabled outside DEMO_MODE=true')
    now=utc_now()
    for actor in FIXTURES['actors']:
        existing=db.get(User,actor['id'])
        if not existing:
            db.add(User(**actor,password_hash=password_hasher.hash(DEMO_PASSWORD),created_at=now))
    db.flush()
    for source in FIXTURES['companies']:
        if not db.scalar(select(Company).where(Company.owner_user_id==source['owner_user_id'],Company.inn==source['inn'])):
            create_company(db,source['owner_user_id'],source,now,seeded=True)
    db.flush()

if __name__=='__main__':
    with SessionLocal.begin() as db:
        seed_demo(db,demo_mode=settings.demo_mode)
    print('Synthetic demo seed ready (idempotent).')

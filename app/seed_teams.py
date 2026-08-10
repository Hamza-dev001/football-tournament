from . import db
from .models import Team

CLUB_NAMES = [
    "Bayern Munich", "Real Madrid", "Barcelona", "Liverpool",
    "Manchester United", "Manchester City", "Chelsea", "Arsenal",
    "AC Milan", "Inter Milan", "Juventus", "PSG",
    "Borussia Dortmund", "Atletico Madrid", "Newcastle United", "Napoli",
    "Al Nassr", "Al Hilal", "Inter Miami", "Botafogo"
]

def seed_teams():
    if Team.query.count() > 0:
        print("⚠️ Teams already seeded.")
        return
    for name in CLUB_NAMES:
        db.session.add(Team(name=name))
    db.session.commit()
    print(f"✅ {len(CLUB_NAMES)} static clubs seeded.")
"""Legt einen Demo-Account mit etwas Inhalt an.

Gedacht für die öffentlich erreichbare Demo: ohne Beiträge wirkt die Seite
kaputt, und ohne Zugangsdaten kommt niemand am Login vorbei.

Aufruf (DATABASE_URL zeigt auf die Zieldatenbank):

    python seed_demo.py

Nochmal ausführen ist unschädlich: existiert der Account schon, passiert nichts.
"""

import datetime

import bcrypt

from database import (
    Comment,
    Like,
    Post,
    SessionLocal,
    User,
    init_db,
)

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "connect-demo"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# Zwei weitere Namen, damit der Feed nicht nur aus einem Autor besteht
PEOPLE = [
    ("demo", "demo@example.com", DEMO_PASSWORD),
    ("lena", "lena@example.com", "connect-demo"),
    ("jonas", "jonas@example.com", "connect-demo"),
]

POSTS = [
    ("lena", "Erster Tag mit Connect. Mal sehen, ob das hier was wird.", 3),
    ("jonas", "Der Feed sortiert tatsächlich nach Leuten, denen man folgt. Nettes Detail.", 2),
    ("demo", "Ich teste gerade die Demo dieser Seite: posten, liken, kommentieren.", 1),
    ("lena", "Wer möchte folgen? Ich folge zurück.", 0),
    ("jonas", "Kleine Projekte sind die besten Projekte.", 4),
]

COMMENTS = [
    ("jonas", 0, "Willkommen!"),
    ("demo", 1, "Funktioniert bei mir auch."),
    ("lena", 2, "Sieht gut aus."),
]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == DEMO_USERNAME).first():
            print("Demo-Account existiert schon, nichts zu tun.")
            return

        users = {}
        for name, email, password in PEOPLE:
            user = User(
                username=name,
                email=email,
                hashed_password=hash_password(password),
                language="de",
            )
            db.add(user)
            users[name] = user
        db.commit()

        now = datetime.datetime.now()
        posts = []
        for name, content, age_days in POSTS:
            post = Post(
                user_id=users[name].id,
                content=content,
                created_at=now - datetime.timedelta(days=age_days),
            )
            db.add(post)
            posts.append(post)
        db.commit()

        # demo folgt lena, damit der Feed etwas zu sortieren hat
        users["demo"].following.append(users["lena"])
        db.add(Like(user_id=users["jonas"].id, post_id=posts[0].id))
        db.add(Like(user_id=users["demo"].id, post_id=posts[0].id))
        db.add(Like(user_id=users["lena"].id, post_id=posts[2].id))
        for name, index, text in COMMENTS:
            db.add(Comment(user_id=users[name].id, post_id=posts[index].id, content=text))
        db.commit()

        print("Demo-Account angelegt: %s / %s" % (DEMO_USERNAME, DEMO_PASSWORD))
        print("%d Nutzer, %d Beiträge" % (len(users), len(posts)))
    finally:
        db.close()


if __name__ == "__main__":
    main()

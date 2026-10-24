"""Demo data for looking at the UI without Telegram: 5 channels with overlapping audiences,
reply chains, daily rhythm and a few spam bots. Real (non-demo) data is never touched.

    python -m scripts.seed_demo          # (re)create demo data
    python -m scripts.seed_demo --clear  # remove demo data only
"""

import asyncio
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.db import SessionLocal, init_db
from app.models import Comment, Event, Job, JobParticipant, PeerNote, TgPeer

USER_BASE = 9_000_000_000  # far above real ids used in tests/demo collisions
CHANNEL_BASE = -1009000000000
CHANNELS = [
    ("Demo Tech", "demo_tech", 52000),
    ("Demo Crypto", "demo_crypto", 31000),
    ("Demo News", "demo_news", 120000),
    ("Demo Design", "demo_design", 18000),
    ("Demo Startups", "demo_startups", 24000),
]
FIRST = ["Алексей", "Мария", "Иван", "Анна", "Дмитрий", "Елена", "Сергей", "Ольга", "Никита", "Катя", "Павел",
         "Юля", "Артём", "Даша", "Kate", "John", "Lena", "Max", "Ник", "Саша"]
LAST = ["Иванов", "Смирнова", "Кузнецов", "Попова", "Волков", "Новикова", "Морозов", "Соколова", "", "", "", "Smith"]
TEXTS = ["Отличный пост!", "Согласен", "А можно подробнее?", "Не согласен, вот почему…", "Спасибо, полезно",
         "Интересно, жду продолжения", "Это уже было", "Кто-нибудь пробовал?", "Ахаха", "+1", "Источник?",
         "Хороший разбор", "Сохранил", "Спорно", "Наконец-то об этом написали"]
SPAM = ["Заработок от 5000 в день, пиши в лс", "Лучший канал про крипту t.me/scam_demo", "Бесплатные курсы: http://spam.example"]


async def clear(db) -> None:
    demo_jobs = (await db.execute(select(Job.id).where(
        (Job.source_id <= CHANNEL_BASE + 0) & (Job.source_id > CHANNEL_BASE - 100)
        | func.json_extract(Job.input, "$.demo").is_(True)
        | (func.json_extract(Job.input, "$.channel") == "https://t.me/demo_channel")
    ))).scalars().all()
    await db.execute(delete(Job).where(Job.id.in_(demo_jobs)))
    await db.execute(delete(TgPeer).where(((TgPeer.id >= USER_BASE) & (TgPeer.id < USER_BASE + 10**6))
                                          | ((TgPeer.id <= CHANNEL_BASE) & (TgPeer.id > CHANNEL_BASE - 100))
                                          | (TgPeer.id.between(100000, 100500))))
    await db.execute(delete(PeerNote).where((PeerNote.peer_id >= USER_BASE) & (PeerNote.peer_id < USER_BASE + 10**6)))
    await db.execute(delete(Event).where((Event.source_id <= CHANNEL_BASE) & (Event.source_id > CHANNEL_BASE - 100)))
    await db.commit()


async def seed(db) -> None:
    rnd = random.Random(7)
    now = datetime.now(UTC).replace(microsecond=0)
    n_users = 1400
    users = []
    for i in range(n_users):
        uid = USER_BASE + i
        uname = None if rnd.random() < 0.3 else f"{rnd.choice(['neo', 'kot', 'dev', 'art', 'max', 'sun'])}_{rnd.randint(10, 9999)}"
        users.append(uid)
        db.add(TgPeer(id=uid, kind="user", first_name=rnd.choice(FIRST), last_name=rnd.choice(LAST) or None,
                      username=uname, usernames=[uname] if uname else [],
                      is_premium=rnd.random() < 0.14, is_bot=rnd.random() < 0.01, is_deleted=rnd.random() < 0.02,
                      is_verified=rnd.random() < 0.005))
    spammers = users[-4:]
    # interests: each user follows 1-3 channels, with tech/startups/design and crypto/news clusters
    clusters = [[0, 4, 3], [1, 2], [2, 0], [3, 4]]
    member: dict[int, list[int]] = defaultdict(list)
    activity = {}
    for uid in users:
        cl = rnd.choice(clusters)
        k = rnd.choices([1, 2, 3], weights=[55, 32, 13])[0]
        chans = set(rnd.sample(cl, min(k, len(cl))))
        if rnd.random() < 0.08:
            chans.add(rnd.randrange(5))
        if uid in spammers:
            chans = set(range(5))
        for c in chans:
            member[c].append(uid)
        activity[uid] = rnd.paretovariate(1.3)

    for ci, (title, uname, subs) in enumerate(CHANNELS):
        cid = CHANNEL_BASE - ci - 1
        db.add(TgPeer(id=cid, kind="channel", title=title, username=uname, usernames=[uname]))
        audience = member[ci]
        weights = [activity[u] for u in audience]
        n_posts = rnd.randint(180, 420)
        start = now - timedelta(days=rnd.randint(300, 700))
        job = Job(tool="comment-collector", status="done", source_id=cid,
                  input={"channel": f"https://t.me/{uname}", "strategy": "auto", "download_avatars": True, "demo": True},
                  started_at=now - timedelta(minutes=5), finished_at=now - timedelta(minutes=ci))
        db.add(job)
        await db.flush()
        stats: dict[int, dict] = {}
        msg_id = 0
        total = 0
        posts_with = 0
        for p in range(n_posts):
            post_id = 10 + p * rnd.randint(1, 3)
            post_date = start + (now - start) * (p / n_posts) + timedelta(hours=rnd.uniform(-10, 10))
            n_comments = int(rnd.paretovariate(1.1) * 3) - 1
            if n_comments <= 0:
                continue
            posts_with += 1
            thread: list[tuple[int, int]] = []
            for _ in range(min(n_comments, 300)):
                sender = rnd.choices(audience, weights)[0]
                # comments cluster in the hours after the post, following a daily rhythm (MSK evening peak)
                d = post_date + timedelta(minutes=rnd.expovariate(1 / 180))
                if rnd.random() < 0.6:
                    d = d.replace(hour=rnd.choices(range(24), weights=[1, 1, 1, 1, 2, 4, 6, 7, 7, 7, 7, 8, 8, 8, 9, 10, 12, 14, 15, 14, 10, 6, 3, 2])[0])
                if d > now:
                    d = now - timedelta(minutes=rnd.randint(1, 500))
                msg_id += 1
                reply_to = None
                if thread and rnd.random() < 0.4:
                    reply_to, target = rnd.choice(thread[-8:])
                    if target == sender:
                        reply_to = None
                text = rnd.choice(SPAM) if sender in spammers else (None if rnd.random() < 0.06 else rnd.choice(TEXTS))
                db.add(Comment(job_id=job.id, msg_id=msg_id, post_id=post_id, sender_id=sender, date=d, text=text, reply_to=reply_to))
                thread.append((msg_id, sender))
                s = stats.setdefault(sender, {"c": 0, "posts": set(), "f": d, "l": d})
                s["c"] += 1
                s["posts"].add(post_id)
                s["f"], s["l"] = min(s["f"], d), max(s["l"], d)
                total += 1
        for uid, s in stats.items():
            db.add(JobParticipant(job_id=job.id, peer_id=uid, comments=s["c"], posts=len(s["posts"]), first_at=s["f"], last_at=s["l"]))
        channel = {"id": cid, "title": title, "username": uname, "photo_id": None, "subscribers": subs,
                   "group_title": f"{title} Chat", "group_username": None}
        job.result = {"channel": channel, "strategy": "fast", "comments": total, "unique_users": len(stats),
                      "posts_total": n_posts, "posts_with_comments": posts_with, "orphaned": 0, "duration_sec": 60.0 + ci * 17}
        job.progress = {"phase": "done", "channel": channel, "strategy": "fast", "comments": total, "unique_users": len(stats),
                        "posts_total": n_posts}
        await db.commit()
        print(f"{title}: {total} comments, {len(stats)} users")
    db.add(PeerNote(peer_id=spammers[0], tags=["спам"], note="Рассылает ссылки во всех каналах"))
    sample = rnd.sample(users[:-4], 6)
    people = [{"peer_id": u, "name": f"Демо {i + 1}", "username": None} for i, u in enumerate(sample)]
    db.add(Event(kind="new_users", title="Demo Tech: +6 новых комментаторов", source_id=CHANNEL_BASE - 1,
                 payload={"count": 6, "people": people, "peer_ids": sample, "path": "/channels/-1009000000001"}))
    db.add(Event(kind="watch", title="Demo Crypto: избранные оставили комментарии", source_id=CHANNEL_BASE - 2,
                 payload={"count": 1, "people": people[:1], "detail": "Демо 1 — 3", "path": "/users?starred=1"}))
    db.add(PeerNote(peer_id=max(activity, key=activity.get), tags=["активист", "VIP"], starred=True))
    await db.commit()


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        await clear(db)
        if "--clear" not in sys.argv:
            await seed(db)


if __name__ == "__main__":
    asyncio.run(main())

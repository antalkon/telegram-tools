"""PDF reports: a person's profile and a source's analytics, for printing or sending on.

Built with fpdf2 and DejaVu Sans (bundled, covers Cyrillic). Everything comes from the same functions as
the API, so a report matches what the panel shows.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights import posts, users
from app.insights.sources import list_sources, source_analytics
from app.insights.users import _user_jobs
from app.models import TgPeer, UsernameCheck
from app.telegram.resolve import TYPE_LABELS

FONTS = Path(__file__).parent / "assets" / "fonts"
ACCENT = (42, 171, 238)
MUTED = (110, 118, 135)
LINE = (220, 224, 230)
CONTACT_LABELS = {"phones": "Телефоны", "emails": "Email", "sites": "Сайты", "inn": "ИНН", "ogrn": "ОГРН",
                  "wallet_ton": "TON", "wallet_eth": "ETH / ERC-20", "wallet_tron": "TRON / TRC-20", "wallet_btc": "BTC"}
DOSSIER_LABELS = {"full_name": "ФИО", "email": "Email", "phone": "Телефон", "country": "Страна", "city": "Город",
                  "address": "Адрес", "passport": "Паспорт"}
FIELD_LABELS = {"first_name": "Имя", "last_name": "Фамилия", "title": "Название", "username": "Username",
                "photo": "Фото", "about": "Bio", "phone": "Телефон"}


def _d(iso: str | None, with_time: bool = False) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%d.%m.%y %H:%M" if with_time else "%d.%m.%Y")


def _n(v: Any) -> str:
    return "—" if v is None else f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)


def _clean(text: str | None, limit: int = 600) -> str:
    """fpdf can't draw characters outside the font (most emoji): drop them."""
    if not text:
        return ""
    t = "".join(ch for ch in text if ord(ch) < 0x2600 or 0x2DE0 <= ord(ch) < 0x1F000)
    return t[:limit] + ("…" if len(t) > limit else "")


class Report(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format="A4")
        self.title_text = title
        self.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.set_auto_page_break(True, margin=16)
        self.set_margins(16, 16, 16)
        self.set_title(title)
        self.set_creator("TG Toolkit")
        self.add_page()

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("DejaVu", "", 7.5)
        self.set_text_color(*MUTED)
        stamp = datetime.now(UTC).strftime("%d.%m.%Y %H:%M UTC")
        self.cell(0, 5, f"TG Toolkit · {self.title_text} · {stamp}", align="L")
        self.cell(0, 5, f"{self.page_no()}/{{nb}}", align="R")

    def h1(self, text: str, sub: str | None = None) -> None:
        self.set_font("DejaVu", "B", 18)
        self.set_text_color(20, 24, 33)
        self.multi_cell(0, 9, _clean(text, 200), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if sub:
            self.set_font("DejaVu", "", 9.5)
            self.set_text_color(*MUTED)
            self.multi_cell(0, 5.5, sub, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def h2(self, text: str) -> None:
        if self.get_y() > self.h - 40:
            self.add_page()
        self.ln(3)
        self.set_font("DejaVu", "B", 12)
        self.set_text_color(*ACCENT)
        self.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def para(self, text: str, size: float = 9.5, muted: bool = False) -> None:
        self.set_font("DejaVu", "", size)
        self.set_text_color(*(MUTED if muted else (20, 24, 33)))
        self.multi_cell(0, size * 0.55, _clean(text, 4000), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def pairs(self, items: list[tuple[str, Any]]) -> None:
        """Label: value lines, skipping empty values."""
        for label, value in items:
            if value in (None, "", [], "—"):
                continue
            self.set_font("DejaVu", "", 9)
            self.set_text_color(*MUTED)
            self.cell(56, 5.5, label)
            self.set_text_color(20, 24, 33)
            self.multi_cell(0, 5.5, _clean(str(value), 800), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def grid(self, headers: list[str], rows: list[list[Any]], widths: list[float]) -> None:
        if not rows:
            self.para("Нет данных", 9, muted=True)
            return
        self.set_font("DejaVu", "", 8.5)
        self.set_text_color(20, 24, 33)
        self.set_fill_color(255, 255, 255)
        self.set_draw_color(*LINE)
        with self.table(col_widths=widths, text_align="LEFT", line_height=4.6, borders_layout="HORIZONTAL_LINES",
                        headings_style=self._heading_style()) as t:
            t.row([h for h in headers])
            for r in rows:
                t.row([_clean("" if v is None else str(v), 400) for v in r])
        self.ln(2)

    def _heading_style(self):
        from fpdf.fonts import FontFace

        return FontFace(emphasis="BOLD", color=MUTED, fill_color=(245, 247, 250))

    def bars(self, points: list[tuple[str, int]], height: float = 32) -> None:
        """A small column chart (activity over time)."""
        if not points:
            return
        if self.get_y() + height + 10 > self.h - 16:
            self.add_page()
        x0, y0 = self.l_margin, self.get_y()
        width = self.w - self.l_margin - self.r_margin
        top = max(v for _, v in points) or 1
        bw = width / len(points)
        self.set_fill_color(*ACCENT)
        for i, (_, v) in enumerate(points):
            h = height * v / top
            self.rect(x0 + i * bw + bw * 0.12, y0 + height - h, bw * 0.76, h, style="F")
        self.set_font("DejaVu", "", 7)
        self.set_text_color(*MUTED)
        self.set_xy(x0, y0 + height + 1)
        self.cell(width / 2, 4, points[0][0])
        self.cell(width / 2, 4, f"{points[-1][0]} · максимум {top:,}".replace(",", " "), align="R")
        self.set_y(y0 + height + 7)


def _contacts(pdf: Report, merged: dict[str, list[dict[str, Any]]]) -> None:
    if not merged:
        pdf.para("Не найдено", 9, muted=True)
        return
    for kind, label in CONTACT_LABELS.items():
        items = merged.get(kind) or []
        if not items:
            continue
        values = []
        for x in items[:15]:
            extra = f" ({x['org']['short_name'] or x['org']['name']})" if x.get("org") else ""
            values.append(f"{x['value']}{extra} ×{x['count']}" if x["count"] > 1 else f"{x['value']}{extra}")
        pdf.pairs([(label, ", ".join(values))])


async def user_report(db: AsyncSession, peer_id: int) -> bytes | None:
    prof = await users.user_profile(db, peer_id)
    if prof is None:
        return None
    p, d, t = prof["peer"], prof["dossier"], prof["totals"]
    pdf = Report(f"Профиль {p['name']}")
    sub = " · ".join(x for x in [f"@{p['username']}" if p["username"] else None, f"ID {p['peer_id']}",
                                  "Premium" if p["is_premium"] else None, "бот" if p["is_bot"] else None,
                                  "удалён" if p["is_deleted"] else None] if x)
    pdf.h1(p["name"], sub)

    pdf.h2("Telegram")
    age = prof.get("account_age")
    age_txt = None
    if age:
        word = {"approx": "≈", "before": "раньше", "after": "после"}[age["kind"]]
        age_txt = f"{word} {_d(age['date'])}" + (f", не позже {_d(age['not_later_than'])}" if age.get("not_later_than") else "")
    pdf.pairs([("Телефон", p.get("phone")), ("Телефоны из bio", ", ".join(prof.get("bio_phones") or [])),
               ("Другие username", ", ".join(f"@{u}" for u in p["usernames"][1:])), ("Аккаунт создан", age_txt),
               ("Метки", ", ".join(p["tags"])), ("Заметка", prof.get("note"))])
    if prof.get("about"):
        pdf.para(f"Bio: {prof['about']}")

    if any(d.get(k) for k in DOSSIER_LABELS) or d.get("files"):
        pdf.h2("Метаданные")
        pdf.pairs([(label, d.get(k)) for k, label in DOSSIER_LABELS.items()])
        if d.get("files"):
            pdf.pairs([("Документы", ", ".join(f["filename"] for f in d["files"]))])

    pdf.h2("Активность")
    pdf.pairs([("Сообщений", _n(t["comments"])), ("Источников", f"{t['sources']} (пишет в {t['active_sources']}, состоит в {t['member_of']})"),
               ("Первое", _d(t["first_at"])), ("Последнее", _d(t["last_at"])),
               ("Индекс подозрительности", prof["signals"].get("spam_score"))])
    pdf.grid(["Источник", "Сообщений", "Место", "Первое", "Последнее"],
              [[s["source"].get("title"), _n(s["comments"]), f"#{s['rank']} из {s['of']}" if s["rank"] else "—",
                _d(s["first_at"]), _d(s["last_at"])] for s in prof["sources"][:30]], [64, 26, 32, 28, 28])

    if prof["channels"]:
        pdf.h2("Его каналы")
        pdf.grid(["Канал", "Как найден", "Участников", "Ссылка"],
                  [[c["title"], ", ".join(c["via"]), _n(c["members_count"]), c["link"]] for c in prof["channels"][:30]],
                  [62, 30, 24, 62])

    _, jobs = await _user_jobs(db, peer_id)
    pdf.h2("Контакты из bio и сообщений")
    _contacts(pdf, await posts.user_contacts(db, peer_id, jobs))

    found = (await db.execute(select(UsernameCheck).where(UsernameCheck.username == (p["username"] or "").lower(),
                                                          UsernameCheck.found.is_(True)))).scalars().all()
    if found:
        pdf.h2(f"@{p['username']} на других сайтах")
        pdf.grid(["Сайт", "Категория", "Ссылка"], [[f.site, f.category, f.url] for f in found[:60]], [45, 35, 98])

    if prof.get("history"):
        pdf.h2("История профиля")
        pdf.grid(["Когда", "Поле", "Было", "Стало"],
                  [[_d(h["changed_at"], True), FIELD_LABELS.get(h["field"], h["field"]), h["old"], h["new"]]
                   for h in prof["history"][:40]], [30, 24, 62, 62])

    conn = await users.connections(db, peer_id, 15)
    if conn["co_commenters"]:
        pdf.h2("Связи: комментирует рядом")
        pdf.grid(["Человек", "Общих постов", "Совпадение"],
                  [[f"{c['name']}" + (f" (@{c['username']})" if c["username"] else ""), _n(c["shared_posts"]),
                    f"{round(c['overlap'] * 100)}%"] for c in conn["co_commenters"]], [110, 34, 34])

    msgs = await users.user_comments(db, peer_id, None, 40)
    if msgs:
        pdf.h2("Последние сообщения")
        pdf.grid(["Дата", "Где", "Текст"], [[_d(m["date"], True), m["source"]["title"], m["text"] or "медиа"] for m in msgs],
                  [30, 40, 108])
    return bytes(pdf.output())


async def source_report(db: AsyncSession, source_id: int) -> bytes | None:
    data = await source_analytics(db, source_id)
    if data is None:
        return None
    s = data["source"]
    peer = await db.get(TgPeer, source_id)
    pdf = Report(f"Отчёт {s['title']}")
    pdf.h1(s["title"], " · ".join(x for x in [f"@{s['username']}" if s.get("username") else None, f"ID {s['id']}",
                                            TYPE_LABELS.get(s.get("type"), s.get("type")), f"собрано {_d(s.get('collected_at'))}"] if x))
    pdf.h2("Сводка")
    pdf.pairs([("Подписчиков", _n(s.get("subscribers"))), ("Авторов", _n(s.get("users"))),
               ("Сообщений", _n(s.get("comments"))), ("Людей всего", _n(s.get("people"))),
               ("Создан", _d(peer.tg_created_at.isoformat()) if peer and peer.tg_created_at else None)])
    if peer and peer.about:
        pdf.para(f"Описание: {peer.about}")

    points = data["timeline"]["points"]
    if points:
        pdf.h2("Активность")
        pdf.bars([(str(x["t"]), x["comments"]) for x in points[-60:]])

    pdf.h2("Самые активные")
    pdf.grid(["Человек", "Сообщений", "Обсуждений"],
              [[f"{u['name']}" + (f" (@{u['username']})" if u["username"] else ""), _n(u["comments"]), _n(u["posts"])]
               for u in data["top_users"][:25]], [118, 30, 30])

    if data["top_posts"]:
        pdf.h2("Самые обсуждаемые")
        pdf.grid(["Обсуждение", "Сообщений", "Людей", "Ссылка"],
                  [[x["label"], _n(x["comments"]), _n(x["users"]), x.get("link")] for x in data["top_posts"][:15]], [62, 24, 20, 72])

    if data["overlap"]:
        titles = {x["id"]: x["title"] for x in await list_sources(db, include_hidden=True)}
        pdf.h2("Пересечения аудитории")
        pdf.grid(["Источник", "Общих людей", "Доля от аудитории"],
                 [[titles.get(o["id"], o["id"]), _n(o["shared"]), f"{round(o['share_of_mine'] * 100)}%"] for o in data["overlap"][:15]],
                 [100, 39, 39])

    page = await posts.list_posts(db, channel=source_id, limit=1)
    if page["total"]:
        pdf.h2(f"Посты ({_n(page['total'])} собрано)")
        top = await posts.list_posts(db, channel=source_id, sort="views", limit=10)
        pdf.grid(["Дата", "Просмотры", "Текст"], [[_d(x["date"]), _n(x["views"]), x["text"] or "медиа"] for x in top["items"]],
                  [24, 24, 130])
        ads = await posts.ads_summary(db, source_id)
        if ads:
            pdf.h2("Реклама в канале")
            pdf.grid(["Рекламодатель", "ИНН", "Постов", "Последний"],
                      [[(a["org"] or {}).get("short_name") or a["advertiser"] or "—", a["inn"], _n(a["posts"]), _d(a["last_at"])]
                       for a in ads[:30]], [88, 30, 24, 36])
        fwd = await posts.forward_sources(db, source_id, 15)
        if fwd:
            pdf.h2("Откуда репостит")
            pdf.grid(["Канал", "Репостов"], [[f["name"] if f["name"] != str(f["peer_id"]) else (f["fallback_name"] or f["peer_id"]), _n(f["posts"])]
                                              for f in fwd], [148, 30])

    contacts = await posts.channel_contacts(db, source_id)
    pdf.h2("Контакты из описания и постов")
    _contacts(pdf, contacts["contacts"])
    return bytes(pdf.output())

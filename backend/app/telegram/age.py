"""Rough registration date of a Telegram account from its user id.

Telegram hands out user ids in increasing order, so known (id, registration date) pairs bound the date
of any id between them. The pairs come from the GetIDs project (python-getids, MIT, © 2019 Jonas Zohren,
© 2020-2023 Amano LLC). They end in late 2021; newer accounts only get "after" that date, plus a "not
later than" bound from the earliest activity of anyone with a higher id in our own base.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ANCHORS_MS = {
    2768409: 1383264000000, 7679610: 1388448000000, 11538514: 1391212000000, 15835244: 1392940000000,
    23646077: 1393459000000, 38015510: 1393632000000, 44634663: 1399334000000, 46145305: 1400198000000,
    54845238: 1411257000000, 63263518: 1414454000000, 101260938: 1425600000000, 101323197: 1426204000000,
    111220210: 1429574000000, 103258382: 1432771000000, 103151531: 1433376000000, 116812045: 1437696000000,
    122600695: 1437782000000, 109393468: 1439078000000, 112594714: 1439683000000, 124872445: 1439856000000,
    130029930: 1441324000000, 125828524: 1444003000000, 133909606: 1444176000000, 157242073: 1446768000000,
    143445125: 1448928000000, 148670295: 1452211000000, 152079341: 1453420000000, 171295414: 1457481000000,
    181783990: 1460246000000, 222021233: 1465344000000, 225034354: 1466208000000, 278941742: 1473465000000,
    285253072: 1476835000000, 294851037: 1479600000000, 297621225: 1481846000000, 328594461: 1482969000000,
    337808429: 1487707000000, 341546272: 1487782000000, 352940995: 1487894000000, 369669043: 1490918000000,
    400169472: 1501459000000, 805158066: 1563208000000, 1974255900: 1634000000000,
}


def _monotonic(pairs: dict[int, int]) -> list[tuple[int, float]]:
    """Sorted by id, dropping pairs whose date goes backwards (a few sample ids are out of order)."""
    out: list[tuple[int, float]] = []
    for uid, ms in sorted(pairs.items()):
        if not out or ms / 1000 >= out[-1][1]:
            out.append((uid, ms / 1000))
    return out


ANCHORS = _monotonic(_ANCHORS_MS)


def estimate(user_id: int) -> dict[str, Any] | None:
    """{"kind": "approx" | "before" | "after", "date": ISO} for a user id; None for channels and chats."""
    if user_id <= 0:
        return None
    first_id, first_ts = ANCHORS[0]
    last_id, last_ts = ANCHORS[-1]
    if user_id < first_id:
        kind, ts = "before", first_ts
    elif user_id > last_id:
        kind, ts = "after", last_ts
    else:
        kind = "approx"
        for (lo_id, lo_ts), (hi_id, hi_ts) in zip(ANCHORS, ANCHORS[1:], strict=False):
            if lo_id <= user_id <= hi_id:
                ts = lo_ts + (user_id - lo_id) / (hi_id - lo_id) * (hi_ts - lo_ts)
                break
    return {"kind": kind, "date": datetime.fromtimestamp(ts, UTC).date().isoformat()}


async def account_age(db: AsyncSession, user_id: int) -> dict[str, Any] | None:
    """The id estimate plus "not later than": the earliest message of anyone in the base whose id is
    this high or higher (registered no earlier than this account, yet already writing)."""
    est = estimate(user_id)
    if est is None:
        return None
    first = (await db.execute(text(
        "SELECT min(first_at) FROM job_participants WHERE peer_id >= :p AND first_at IS NOT NULL"), {"p": user_id})).scalar()
    if first:
        est["not_later_than"] = str(first)[:10]
    return est

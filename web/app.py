"""The JSON API behind the Vue single-page app, served at /.

The page's centre is the split screen: the same evaluation of the hosting data,
once straight from PostgreSQL and once through the cache-aside path, side by
side. Below it a price can be changed in PostgreSQL to show what a cache does to
consistency, and every table can be browsed.

The request path is the whole point: ask Redis first, and only on a miss go to
PostgreSQL, putting the answer into Redis on the way back. Every response
carries the time it took and where it came from, so the difference is visible
in the page itself.
"""

import datetime
import decimal
import functools
import json
import os
import time
from contextlib import contextmanager

import psycopg
import redis
from flask import Flask, jsonify, request, send_from_directory
from psycopg.rows import dict_row

# Every key this application puts into Redis starts with one of these. They are
# the list 'Cache leeren' walks, so nothing else in Redis is touched.
COUNTS_KEY = "tables"
CACHE_MUSTER = [COUNTS_KEY, "table:*", "auswertung:*"]

# The entries that contain a price. Changing a price in PostgreSQL leaves them
# stale until they expire -- or until they are invalidated on purpose.
PREIS_MUSTER = ["auswertung:*"]
CACHE_TTL = int(os.environ.get("CACHE_TTL", 300))

# How many rows a browse page returns by default. The tables hold up to a
# million rows; nothing here may try to send all of them to the browser.
PAGE_SIZE = 100

DSN = (
    f"host={os.environ.get('PG_HOST', '127.0.0.1')} "
    f"dbname={os.environ.get('PG_DATABASE', 'hostingdb')} "
    f"user={os.environ.get('PG_USER', 'app')} "
    f"password={os.environ.get('PG_PASSWORD', '')}"
)

cache = redis.Redis(
    host=os.environ.get("REDIS_HOST", "127.0.0.1"),
    port=6379,
    socket_timeout=2,
    decode_responses=True,
)

app = Flask(__name__, static_url_path="/static")


# The only table names the API accepts. Nothing else gets through, and that is
# what makes it safe to put the name directly into the SQL text further down: it
# can only ever be one of these six literals, never something a caller sent.
TABLES = {
    "kunde": {"label": "Kunde", "order": "kunde_nr"},
    "anbieter": {"label": "Anbieter", "order": "anbieter_id"},
    "dienst": {"label": "Dienst", "order": "dienst_code"},
    "domain": {"label": "Domain", "order": "domain_id"},
    "domain_nameserver": {"label": "Nameserver", "order": "domain_id, hostname"},
    "domain_dienst": {"label": "Zuordnung", "order": "domain_id, dienst_code"},
}


# ----------------------------------------------------------------- plumbing


@contextmanager
def db():
    """One connection per request. A pool would be faster and is not the point."""
    with psycopg.connect(DSN) as connection:
        yield connection


def fetch(connection, sql, params=None):
    """Run one query and return its rows as plain dicts.

    params stays None when there is nothing to bind. psycopg only reads '%' as
    the start of a placeholder once parameters are passed, and SQL written by
    hand is exactly where a literal per cent sign turns up.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        return [plain(row) for row in cursor.fetchall()]


def plain(row):
    """psycopg hands back Decimal and date; Flask's JSON encoder knows neither."""
    result = {}
    for key, value in row.items():
        if isinstance(value, decimal.Decimal):
            result[key] = float(value)
        elif isinstance(value, (datetime.date, datetime.datetime)):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def as_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def api(view):
    """Time every API call and turn a failure into JSON the page can display.

    Without this an empty database would give the browser a bare 500 and the page
    would just sit there; now it says 'relation domain does not exist'.
    """

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            payload = view(*args, **kwargs)
        except ValueError as exception:
            return jsonify(fehler=str(exception)), 400
        except Exception as exception:  # shown on the page; this is a lab
            return jsonify(fehler=str(exception)), 500
        payload["ms"] = round((time.perf_counter() - started) * 1000, 1)
        return jsonify(payload)

    return wrapper


def cache_aside(schluessel, erzeuge, mit_cache=True):
    """The pattern this whole lab is about, in one place.

    Returns (payload, herkunft). 'herkunft' is what the page puts on screen:
    where the answer came from, and how long PostgreSQL needed to produce it.
    On a hit that second number is the one stored when the entry was written --
    without it a hit is merely fast, with it the difference is visible.
    """

    def von_postgres():
        started = time.perf_counter()
        daten = erzeuge()
        return daten, round((time.perf_counter() - started) * 1000, 1)

    if not mit_cache:
        daten, ms = von_postgres()
        return daten, {"quelle": "PostgreSQL", "treffer": False, "ms_postgres": ms,
                       "hinweis": "Cache übersprungen"}

    try:
        roh = cache.get(schluessel)
    except redis.RedisError:
        # A cache is an optimisation, not a dependency: without it the page is
        # slow, but it still works.
        daten, ms = von_postgres()
        return daten, {"quelle": "PostgreSQL", "treffer": False, "ms_postgres": ms,
                       "hinweis": "Redis nicht erreichbar"}

    if roh is not None:
        eintrag = json.loads(roh)
        # The age is what makes a stale answer explainable: this is how long
        # ago PostgreSQL was asked, and how long Redis will keep answering.
        alter = round(time.time() - eintrag.get("gespeichert", time.time()))
        return eintrag["daten"], {"quelle": "Redis", "treffer": True,
                                  "ms_postgres": eintrag["ms_postgres"],
                                  "alter_s": alter,
                                  "rest_s": max(CACHE_TTL - alter, 0)}

    daten, ms = von_postgres()
    try:
        cache.setex(schluessel, CACHE_TTL,
                    json.dumps({"daten": daten, "ms_postgres": ms,
                                "gespeichert": time.time()}))
    except redis.RedisError:
        pass
    return daten, {"quelle": "PostgreSQL", "treffer": False, "ms_postgres": ms,
                   "alter_s": 0, "rest_s": CACHE_TTL}


def invalidieren(muster_liste):
    """Drop every key matching one of the patterns. Returns how many there were."""
    entfernt = 0
    try:
        for muster in muster_liste:
            schluessel = list(cache.scan_iter(match=muster, count=500))
            if schluessel:
                entfernt += cache.delete(*schluessel)
    except redis.RedisError:
        pass
    return entfernt


def cache_leeren():
    """Drop every key this application owns. Returns how many there were."""
    return invalidieren(CACHE_MUSTER)


def block(titel, zeilen):
    """One output panel: a caption and rows, columns taken from the first row."""
    return {"titel": titel, "spalten": list(zeilen[0]) if zeilen else [], "zeilen": zeilen}


# ------------------------------------------------------------------- tables


def uncached_counts():
    with db() as connection:
        # The table name comes from TABLES, never from the request -- see there.
        return {
            name: fetch(connection, f"SELECT count(*) AS n FROM {name}")[0]["n"]
            for name in TABLES
        }


def mit_cache():
    """False when the request carries ?nocache -- then it goes straight to PostgreSQL."""
    return "nocache" not in request.args


@app.get("/api/tables")
@api
def api_tables():
    counts, herkunft = cache_aside(COUNTS_KEY, uncached_counts, mit_cache())
    return {
        "cache": herkunft,
        # So the page can name the TTL instead of hard-coding it next to the
        # value that actually governs it, in ansible/group_vars/all.yml.
        "ttl_sekunden": CACHE_TTL,
        "tabellen": [
            {"name": name, "label": meta["label"], "zeilen": counts[name]}
            for name, meta in TABLES.items()
        ],
    }


def tabelle_von_postgres(name, limit, offset):
    with db() as connection:
        zeilen = fetch(
            connection,
            # Name and sort order come from TABLES; limit and offset are bound.
            f"SELECT * FROM {name} ORDER BY {TABLES[name]['order']} "
            "LIMIT %(limit)s OFFSET %(offset)s",
            {"limit": limit, "offset": offset},
        )
    return {
        "name": name,
        "label": TABLES[name]["label"],
        "offset": offset,
        "limit": limit,
        "spalten": list(zeilen[0]) if zeilen else [],
        "zeilen": zeilen,
    }


@app.get("/api/table/<name>")
@api
def api_table(name):
    if name not in TABLES:
        raise ValueError(f"Unbekannte Tabelle: {name}")
    limit = as_int(request.args.get("limit"), PAGE_SIZE, 1, 500)
    offset = as_int(request.args.get("offset"), 0, 0, 10_000_000)

    # Without an index, even ORDER BY ... LIMIT 50 has to sort the whole table,
    # so a browse page is worth caching too.
    daten, herkunft = cache_aside(
        f"table:{name}:{offset}:{limit}",
        lambda: tabelle_von_postgres(name, limit, offset),
        mit_cache(),
    )
    return {**daten, "cache": herkunft}


# --------------------------------------------------------------- Auswertung
#
# The centre of the page. One evaluation of the hosting data, narrowed down by
# three filters. Without secondary indexes every run reads domain and
# domain_dienst in full -- 1.5 million rows -- whatever the filter says.

# The values the 'ablauf' filter accepts, and the SQL each one adds. Fixed
# fragments, never text from the request; the number of days is bound.
ABLAUF = {
    "alle": None,
    "abgelaufen": "d.ablauf_datum < current_date",
    "30": "d.ablauf_datum BETWEEN current_date AND current_date + 30",
    "90": "d.ablauf_datum BETWEEN current_date AND current_date + 90",
    "365": "d.ablauf_datum BETWEEN current_date AND current_date + 365",
}


def auswertung_filter():
    """Read the filter from the query string in one canonical form.

    The canonical form is also the cache key: the same filter in a different
    order has to hit the same entry, and any other filter must not.
    """
    hoster = as_int(request.args.get("hoster"), None, 1, 2_000_000_000)
    dienste = sorted({d.strip().upper() for d in
                      (request.args.get("dienste") or "").split(",") if d.strip()})
    if any(len(d) > 20 for d in dienste):
        raise ValueError("Ungültiger Dienstcode")
    ablauf = request.args.get("ablauf") or "alle"
    if ablauf not in ABLAUF:
        raise ValueError(f"Unbekannter Ablauf-Filter: {ablauf}")
    return hoster, dienste, ablauf


def auswertung_von_postgres(hoster, dienste, ablauf):
    bedingungen = ["TRUE"]
    params = {}
    if hoster is not None:
        bedingungen.append("d.hoster_id = %(hoster)s")
        params["hoster"] = hoster
    if dienste:
        bedingungen.append("dd.dienst_code = ANY(%(dienste)s)")
        params["dienste"] = dienste
    if ABLAUF[ablauf]:
        bedingungen.append(ABLAUF[ablauf])

    # Every row a filter lets through: one per domain and service. The WHERE
    # clause is assembled from the fixed fragments above only.
    auswahl = f"""
        WITH auswahl AS (
            SELECT d.domain_id, d.kunde_nr, d.hoster_id,
                   s.dienst_code, s.bezeichnung, s.preis_monat
            FROM domain d
            JOIN domain_dienst dd ON dd.domain_id  = d.domain_id
            JOIN dienst s         ON s.dienst_code = dd.dienst_code
            WHERE {' AND '.join(bedingungen)}
        )
    """
    with db() as connection:
        kennzahlen = fetch(connection, auswahl + """
            SELECT count(DISTINCT domain_id) AS domains,
                   count(DISTINCT kunde_nr)  AS kunden,
                   count(*)                  AS zuordnungen,
                   coalesce(sum(preis_monat), 0) AS monatlich_chf
            FROM auswahl
        """, params)
        nach_dienst = fetch(connection, auswahl + """
            SELECT dienst_code AS dienst, bezeichnung,
                   max(preis_monat) AS preis_chf,
                   count(*)         AS domains,
                   sum(preis_monat) AS monatlich_chf
            FROM auswahl
            GROUP BY dienst_code, bezeichnung
            ORDER BY dienst_code
        """, params)
        nach_hoster = fetch(connection, auswahl + """
            SELECT h.name AS hoster,
                   count(DISTINCT a.domain_id) AS domains,
                   sum(a.preis_monat)          AS monatlich_chf
            FROM auswahl a
            JOIN anbieter h ON h.anbieter_id = a.hoster_id
            GROUP BY h.name
            ORDER BY h.name
        """, params)

    return {
        "kennzahlen": kennzahlen[0],
        "bloecke": [
            block("Nach Dienst", nach_dienst),
            block("Nach Hoster", nach_hoster),
        ],
    }


@app.get("/api/auswertung")
@api
def api_auswertung():
    hoster, dienste, ablauf = auswertung_filter()
    daten, herkunft = cache_aside(
        f"auswertung:{hoster or 'alle'}:{','.join(dienste) or 'alle'}:{ablauf}",
        lambda: auswertung_von_postgres(hoster, dienste, ablauf),
        mit_cache(),
    )
    return {**daten, "cache": herkunft}


@app.get("/api/optionen")
@api
def api_optionen():
    """What the filters offer, and the current prices.

    Deliberately not cached: the tables are tiny, and the price form has to show
    what PostgreSQL holds right now, not what Redis remembers.
    """
    with db() as connection:
        anbieter = fetch(connection,
                         "SELECT anbieter_id AS id, name FROM anbieter ORDER BY name")
        dienste = fetch(connection,
                        "SELECT dienst_code AS code, bezeichnung, preis_monat "
                        "FROM dienst ORDER BY dienst_code")
    return {"anbieter": anbieter, "dienste": dienste, "ttl_sekunden": CACHE_TTL}


# ------------------------------------------------------ Konsistenz: schreiben


@app.post("/api/dienst/<code>/preis")
@api
def api_preis(code):
    """Change a price in PostgreSQL -- and, only if asked to, in the cache too.

    Cache-aside only ever reads. Whoever writes to the database has to throw
    the affected entries away, otherwise Redis keeps serving the old price until
    the TTL runs out. The page lets both cases be shown on purpose.
    """
    eingabe = request.get_json(silent=True) or {}
    try:
        preis = round(float(eingabe.get("preis")), 2)
    except (TypeError, ValueError):
        raise ValueError("Preis fehlt oder ist keine Zahl")
    if not 0 <= preis <= 100_000:
        raise ValueError("Preis muss zwischen 0 und 100'000 CHF liegen")

    with db() as connection:
        zeilen = fetch(
            connection,
            "UPDATE dienst SET preis_monat = %(preis)s WHERE dienst_code = %(code)s "
            "RETURNING dienst_code AS code, bezeichnung, preis_monat",
            {"preis": preis, "code": code},
        )
    if not zeilen:
        raise ValueError(f"Kein Dienst mit dem Code {code}")

    entfernt = invalidieren(PREIS_MUSTER) if eingabe.get("invalidieren") else 0
    return {"dienst": zeilen[0], "invalidiert": bool(eingabe.get("invalidieren")),
            "entfernt": entfernt}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/cache/clear")
@api
def api_cache_clear():
    """Empty the cache from the single-page app, which stays on the page."""
    return {"entfernt": cache_leeren()}


@app.post("/api/cache/preise")
@api
def api_cache_preise():
    """Drop only the entries that contain a price -- the targeted invalidation."""
    return {"entfernt": invalidieren(PREIS_MUSTER)}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

"""Two pages over the same database.

  /         a Vue single-page app: browse every table, search an element, and
            see everything connected to it.
  /report   the cache-aside report from db/query.sql -- what the lab measures.

The request path of /report is the whole point: ask Redis first, and only on a
miss go to PostgreSQL, putting the answer into Redis on the way back.

The browser pages run plain queries instead, with one exception: the row counts
per table are cached, because counting 2.5 million rows in a schema that has no
secondary indexes is slow enough to notice. Every response carries the time it
took, so the cost of a missing index is visible in the page itself.
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
from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory
from psycopg.rows import dict_row

# Every key this application puts into Redis starts with one of these. They are
# the list 'Cache leeren' walks, so nothing else in Redis is touched.
REPORT_KEY = "report"
COUNTS_KEY = "tables"
CACHE_MUSTER = [REPORT_KEY, COUNTS_KEY, "table:*", "search:*", "detail:*"]
CACHE_TTL = int(os.environ.get("CACHE_TTL", 300))
QUERY_FILE = os.environ.get("QUERY_FILE", "query.sql")

# How many rows a browse page and a detail block return at most. The tables hold
# up to a million rows; nothing here may try to send all of them to the browser.
PAGE_SIZE = 50
BLOCK_LIMIT = 200
SEARCH_LIMIT = 8

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
        return eintrag["daten"], {"quelle": "Redis", "treffer": True,
                                  "ms_postgres": eintrag["ms_postgres"]}

    daten, ms = von_postgres()
    try:
        cache.setex(schluessel, CACHE_TTL,
                    json.dumps({"daten": daten, "ms_postgres": ms}))
    except redis.RedisError:
        pass
    return daten, {"quelle": "PostgreSQL", "treffer": False, "ms_postgres": ms}


def cache_leeren():
    """Drop every key this application owns. Returns how many there were."""
    entfernt = 0
    try:
        for muster in CACHE_MUSTER:
            schluessel = list(cache.scan_iter(match=muster, count=500))
            if schluessel:
                entfernt += cache.delete(*schluessel)
    except redis.RedisError:
        pass
    return entfernt


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


# ------------------------------------------------------------------- search

# One query per kind of element. %(term)s appears more than once in some of
# them, which is why the parameters are named rather than positional.
SEARCH = {
    "domain": """
        SELECT domain_id::text AS id, name AS label, 'Domain' AS art
        FROM domain
        WHERE name ILIKE %(term)s
        ORDER BY name LIMIT %(limit)s
    """,
    "kunde": """
        SELECT kunde_nr AS id, name AS label, 'Kunde ' || kunde_nr AS art
        FROM kunde
        WHERE name ILIKE %(term)s OR kunde_nr ILIKE %(term)s
        ORDER BY name LIMIT %(limit)s
    """,
    "anbieter": """
        SELECT anbieter_id::text AS id, name AS label, 'Anbieter' AS art
        FROM anbieter
        WHERE name ILIKE %(term)s
        ORDER BY name LIMIT %(limit)s
    """,
    "dienst": """
        SELECT dienst_code AS id, bezeichnung AS label,
               'Dienst ' || dienst_code AS art
        FROM dienst
        WHERE dienst_code ILIKE %(term)s OR bezeichnung ILIKE %(term)s
        ORDER BY dienst_code LIMIT %(limit)s
    """,
    "nameserver": """
        SELECT hostname AS id, hostname AS label, 'Nameserver' AS art
        FROM domain_nameserver
        WHERE hostname ILIKE %(term)s
        GROUP BY hostname
        ORDER BY hostname LIMIT %(limit)s
    """,
}


def suche_in_postgres(term):
    params = {"term": f"%{term}%", "limit": SEARCH_LIMIT}
    treffer = []
    with db() as connection:
        for typ, sql in SEARCH.items():
            for row in fetch(connection, sql, params):
                treffer.append({"typ": typ, **row})
    return treffer


@app.get("/api/search")
@api
def api_search():
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return {"treffer": [], "begriff": term, "cache": None}

    daten, herkunft = cache_aside(
        f"search:{term.lower()}", lambda: suche_in_postgres(term), mit_cache()
    )
    return {"treffer": daten, "begriff": term, "cache": herkunft}


# ------------------------------------------------------------------- detail


def detail_domain(connection, ident):
    domain_id = as_int(ident, None, 1, 2_000_000_000)
    if domain_id is None:
        raise ValueError(f"Keine gültige domain_id: {ident}")

    stamm = fetch(
        connection,
        """
        SELECT d.name AS domain, d.ablauf_datum,
               k.kunde_nr, k.name AS kunde, k.kontakt,
               r.name AS registrar,
               h.name AS hoster, h.support_telefon, h.rechenzentrum
        FROM domain d
        JOIN kunde k    ON k.kunde_nr    = d.kunde_nr
        JOIN anbieter r ON r.anbieter_id = d.registrar_id
        JOIN anbieter h ON h.anbieter_id = d.hoster_id
        WHERE d.domain_id = %(id)s
        """,
        {"id": domain_id},
    )
    if not stamm:
        raise ValueError(f"Keine Domain mit domain_id {domain_id}")

    nameserver = fetch(
        connection,
        "SELECT hostname FROM domain_nameserver WHERE domain_id = %(id)s "
        "ORDER BY hostname",
        {"id": domain_id},
    )
    dienste = fetch(
        connection,
        """
        SELECT s.dienst_code, s.bezeichnung, s.preis_monat
        FROM domain_dienst dd
        JOIN dienst s ON s.dienst_code = dd.dienst_code
        WHERE dd.domain_id = %(id)s
        ORDER BY s.dienst_code
        """,
        {"id": domain_id},
    )
    summe = sum(zeile["preis_monat"] for zeile in dienste)

    return {
        "titel": stamm[0]["domain"],
        "art": "Domain",
        "bloecke": [
            block("Stammdaten", stamm),
            block("Nameserver", nameserver),
            block("Bezogene Dienste", dienste),
            block("Summe", [{"dienste": len(dienste), "monatlich_chf": summe}]),
        ],
    }


def detail_kunde(connection, ident):
    stamm = fetch(
        connection,
        "SELECT kunde_nr, name, kontakt FROM kunde WHERE kunde_nr = %(id)s",
        {"id": ident},
    )
    if not stamm:
        raise ValueError(f"Kein Kunde mit der Nummer {ident}")

    kennzahlen = fetch(
        connection,
        """
        SELECT count(DISTINCT d.domain_id) AS domains,
               count(dd.dienst_code)       AS dienste,
               coalesce(sum(s.preis_monat), 0) AS monatlich_chf
        FROM domain d
        LEFT JOIN domain_dienst dd ON dd.domain_id = d.domain_id
        LEFT JOIN dienst s         ON s.dienst_code = dd.dienst_code
        WHERE d.kunde_nr = %(id)s
        """,
        {"id": ident},
    )
    domains = fetch(
        connection,
        """
        SELECT d.name AS domain, d.ablauf_datum,
               r.name AS registrar, h.name AS hoster
        FROM domain d
        JOIN anbieter r ON r.anbieter_id = d.registrar_id
        JOIN anbieter h ON h.anbieter_id = d.hoster_id
        WHERE d.kunde_nr = %(id)s
        ORDER BY d.name
        LIMIT %(limit)s
        """,
        {"id": ident, "limit": BLOCK_LIMIT},
    )

    return {
        "titel": stamm[0]["name"],
        "art": "Kunde",
        "bloecke": [
            block("Stammdaten", stamm),
            block("Kennzahlen", kennzahlen),
            block(f"Domains (max. {BLOCK_LIMIT})", domains),
        ],
    }


def detail_anbieter(connection, ident):
    anbieter_id = as_int(ident, None, 1, 2_000_000_000)
    if anbieter_id is None:
        raise ValueError(f"Keine gültige anbieter_id: {ident}")

    stamm = fetch(
        connection,
        "SELECT anbieter_id, name, support_telefon, rechenzentrum "
        "FROM anbieter WHERE anbieter_id = %(id)s",
        {"id": anbieter_id},
    )
    if not stamm:
        raise ValueError(f"Kein Anbieter mit anbieter_id {anbieter_id}")

    kennzahlen = fetch(
        connection,
        """
        SELECT count(*) FILTER (WHERE registrar_id = %(id)s) AS als_registrar,
               count(*) FILTER (WHERE hoster_id    = %(id)s) AS als_hoster
        FROM domain
        WHERE registrar_id = %(id)s OR hoster_id = %(id)s
        """,
        {"id": anbieter_id},
    )
    domains = fetch(
        connection,
        """
        SELECT d.name AS domain, k.name AS kunde, d.ablauf_datum
        FROM domain d
        JOIN kunde k ON k.kunde_nr = d.kunde_nr
        WHERE d.hoster_id = %(id)s
        ORDER BY d.name
        LIMIT %(limit)s
        """,
        {"id": anbieter_id, "limit": BLOCK_LIMIT},
    )

    return {
        "titel": stamm[0]["name"],
        "art": "Anbieter",
        "bloecke": [
            block("Stammdaten", stamm),
            block("Kennzahlen", kennzahlen),
            block(f"Gehostete Domains (max. {BLOCK_LIMIT})", domains),
        ],
    }


def detail_dienst(connection, ident):
    stamm = fetch(
        connection,
        "SELECT dienst_code, bezeichnung, preis_monat FROM dienst "
        "WHERE dienst_code = %(id)s",
        {"id": ident},
    )
    if not stamm:
        raise ValueError(f"Kein Dienst mit dem Code {ident}")

    kennzahlen = fetch(
        connection,
        """
        SELECT count(*) AS zuordnungen,
               count(*) * max(s.preis_monat) AS monatlich_chf
        FROM domain_dienst dd
        JOIN dienst s ON s.dienst_code = dd.dienst_code
        WHERE dd.dienst_code = %(id)s
        """,
        {"id": ident},
    )
    domains = fetch(
        connection,
        """
        SELECT d.name AS domain, k.name AS kunde
        FROM domain_dienst dd
        JOIN domain d ON d.domain_id = dd.domain_id
        JOIN kunde k  ON k.kunde_nr  = d.kunde_nr
        WHERE dd.dienst_code = %(id)s
        ORDER BY d.name
        LIMIT %(limit)s
        """,
        {"id": ident, "limit": BLOCK_LIMIT},
    )

    return {
        "titel": stamm[0]["bezeichnung"],
        "art": "Dienst",
        "bloecke": [
            block("Stammdaten", stamm),
            block("Kennzahlen", kennzahlen),
            block(f"Domains mit diesem Dienst (max. {BLOCK_LIMIT})", domains),
        ],
    }


def detail_nameserver(connection, ident):
    kennzahlen = fetch(
        connection,
        "SELECT count(*) AS domains FROM domain_nameserver WHERE hostname = %(id)s",
        {"id": ident},
    )
    if not kennzahlen or kennzahlen[0]["domains"] == 0:
        raise ValueError(f"Kein Nameserver {ident} in der Datenbank")

    domains = fetch(
        connection,
        """
        SELECT d.name AS domain, k.name AS kunde, h.name AS hoster
        FROM domain_nameserver ns
        JOIN domain d   ON d.domain_id    = ns.domain_id
        JOIN kunde k    ON k.kunde_nr     = d.kunde_nr
        JOIN anbieter h ON h.anbieter_id  = d.hoster_id
        WHERE ns.hostname = %(id)s
        ORDER BY d.name
        LIMIT %(limit)s
        """,
        {"id": ident, "limit": BLOCK_LIMIT},
    )

    return {
        "titel": ident,
        "art": "Nameserver",
        "bloecke": [
            block("Kennzahlen", kennzahlen),
            block(f"Domains auf diesem Nameserver (max. {BLOCK_LIMIT})", domains),
        ],
    }


DETAIL = {
    "domain": detail_domain,
    "kunde": detail_kunde,
    "anbieter": detail_anbieter,
    "dienst": detail_dienst,
    "nameserver": detail_nameserver,
}


def detail_von_postgres(typ, ident):
    with db() as connection:
        return DETAIL[typ](connection, ident)


@app.get("/api/detail/<typ>/<path:ident>")
@api
def api_detail(typ, ident):
    if typ not in DETAIL:
        raise ValueError(f"Unbekannte Art: {typ}")

    # This is where the lab earns its name: the detail of a customer or a
    # nameserver reads hundreds of thousands of rows without an index. From
    # Redis the same answer comes back in about a millisecond.
    daten, herkunft = cache_aside(
        f"detail:{typ}:{ident}",
        lambda: detail_von_postgres(typ, ident),
        mit_cache(),
    )
    return {**daten, "cache": herkunft}


# ------------------------------------------------------- the cache-aside report


def query_postgres():
    """Run db/query.sql against PostgreSQL and return the rows as dicts."""
    sql = ""
    if os.path.exists(QUERY_FILE):
        with open(QUERY_FILE) as handle:
            sql = handle.read().strip()
    if not sql:
        raise RuntimeError(
            f"{QUERY_FILE} is missing or empty. "
            "Write db/query.sql and run 'vagrant provision web'."
        )

    # Not fetch(): a statement that is not a SELECT has no result set, and
    # fetchall() would raise a psycopg error instead of saying what is wrong.
    with db() as connection, connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql)
        if cursor.description is None:
            raise RuntimeError(
                f"{QUERY_FILE} returned no result set - it has to be a SELECT."
            )
        return [plain(row) for row in cursor.fetchall()]


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/report")
def report_page():
    started = time.perf_counter()
    try:
        rows, herkunft = cache_aside(REPORT_KEY, query_postgres, mit_cache())
        source = f"{herkunft['quelle']} (PostgreSQL: {herkunft['ms_postgres']} ms)"
        error = None
    except Exception as exception:  # shown on the page; this is a lab
        rows, source, error = [], "fehlgeschlagen", str(exception)
    elapsed_ms = (time.perf_counter() - started) * 1000

    # 'quelle', not 'source': render_template_string's own first parameter is
    # called source, and passing source= as context collides with it.
    return render_template_string(
        PAGE,
        rows=rows,
        columns=list(rows[0]) if rows else [],
        quelle=source,
        elapsed_ms=elapsed_ms,
        error=error,
        ttl=CACHE_TTL,
    )


@app.post("/invalidate")
def invalidate():
    """Empty the cache from the report page, which posts a plain HTML form."""
    cache_leeren()
    return redirect(request.form.get("zurueck", "/report"))


@app.post("/api/cache/clear")
@api
def api_cache_clear():
    """Empty the cache from the single-page app, which stays on the page."""
    return {"entfernt": cache_leeren()}


PAGE = """
<!doctype html>
<title>Verfügbarkeitsbericht</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; color: #222; }
  .bar { display: flex; gap: 1rem; align-items: baseline; margin-bottom: 1.5rem; }
  .source { font-weight: 600; }
  .time { font-variant-numeric: tabular-nums; }
  .error { background: #fdd; padding: 1rem; border-radius: 4px; }
  table { border-collapse: collapse; }
  th, td { border: 1px solid #ddd; padding: 0.3rem 0.7rem; text-align: left; }
  th { background: #f4f4f4; }
  td { font-variant-numeric: tabular-nums; }
</style>

<h1>Verfügbarkeitsbericht</h1>

<div class="bar">
  <span class="source">{{ quelle }}</span>
  <span class="time">{{ "%.1f"|format(elapsed_ms) }} ms</span>
  <span>{{ rows|length }} Zeilen</span>
  <span>TTL {{ ttl }} s</span>
  <a href="/report">neu laden</a>
  <a href="/report?nocache">ohne Cache</a>
  <a href="/">Datenbank-Browser</a>
  <form method="post" action="/invalidate"><button>Cache leeren</button></form>
</div>

{% if error %}
  <p class="error">{{ error }}</p>
{% else %}
  <table>
    <tr>{% for column in columns %}<th>{{ column }}</th>{% endfor %}</tr>
    {% for row in rows %}
      <tr>{% for column in columns %}<td>{{ row[column] }}</td>{% endfor %}</tr>
    {% endfor %}
  </table>
{% endif %}
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

import hashlib
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

EMAIL = "24f3004574@ds.study.iitm.ac.in".strip().lower()


@app.get("/")
def root():
    return {"ok": True, "endpoints": ["/effective-config", "/mcp", "/ask"]}


# ---------------------------------------------------------------- Q6
DEFAULTS = {"port": 8000, "workers": 1, "debug": False, "log_level": "info",
            "api_key": "default-secret-000"}
YAML_DEV = {"workers": 2, "debug": False}                       # config.development.yaml
DOTENV = {"APP_PORT": "8696", "NUM_WORKERS": "10",
          "APP_DEBUG": "true", "APP_LOG_LEVEL": "debug"}        # .env
OS_ENV = {"APP_LOG_LEVEL": "debug"}                             # OS env (APP_* prefix)
ALIASES = {"num_workers": "workers"}


def norm_key(k: str) -> str:
    k = k.strip()
    if k.upper().startswith("APP_"):
        k = k[4:]
    k = k.lower()
    return ALIASES.get(k, k)


def coerce(key: str, v):
    if key in ("port", "workers"):
        try:
            return int(str(v).strip())
        except ValueError:
            return v
    if key == "debug":
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes", "on")
    return str(v)


@app.get("/effective-config")
def effective_config(request: Request):
    cfg = dict(DEFAULTS)
    for layer in (YAML_DEV, DOTENV, OS_ENV):
        for k, v in layer.items():
            cfg[norm_key(k)] = v
    for item in request.query_params.getlist("set"):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        cfg[norm_key(k)] = v
    out = {k: coerce(k, v) for k, v in cfg.items()}
    out["api_key"] = "****"
    return out


# ---------------------------------------------------------------- Q14 (MCP over HTTP)
TOOL = {
    "name": "solve_challenge",
    "description": "Returns the exam response for the current request's challenge header.",
    "inputSchema": {"type": "object", "properties": {}},
}


def handle_rpc(msg: dict, headers):
    method = msg.get("method")
    mid = msg.get("id")
    if mid is None:                       # notification -> no response
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion") or "2025-03-26"
        return ok({"protocolVersion": ver,
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "ledger-exam-server", "version": "1.0.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [TOOL]})
    if method == "tools/call":
        name = (msg.get("params") or {}).get("name")
        if name != "solve_challenge":
            return err(-32602, f"Unknown tool: {name}")
        challenge = headers.get("x-exam-challenge", "")
        text = hashlib.sha256(f"{challenge}:{EMAIL}".encode()).hexdigest()[:16]
        return ok({"content": [{"type": "text", "text": text}], "isError": False})
    return err(-32601, f"Method not found: {method}")


@app.post("/mcp")
async def mcp(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    if isinstance(body, list):
        res = [r for r in (handle_rpc(m, request.headers) for m in body) if r is not None]
        return JSONResponse(res) if res else Response(status_code=202)
    res = handle_rpc(body, request.headers)
    return Response(status_code=202) if res is None else JSONResponse(res)


@app.get("/mcp")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.delete("/mcp")
def mcp_delete():
    return Response(status_code=200)


# ---------------------------------------------------------------- Q15 (Ledger Agent)
import os, re, time, json
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict
import httpx

IST = timezone(timedelta(hours=5, minutes=30))     # Asia/Kolkata has no DST

# The Q15 URL from the task (path=/ at the end). A fallback URL is tried if the first fails.
LEDGER_URLS = [u for u in [
    os.environ.get("LEDGER_URL", ""),
    "https://exam.sanand.workers.dev/questionData?email=24f3004574%40ds.study.iitm.ac.in&quizSign=qX%2FCks0uznTfgi1wCWHXVfReDfox62ChJa3Uk1llhJfze5gZeC1FLBSASL4evPLBhloAuxz6cP4HFarqn2kAhU1wYRuRISE87ri4AiMGngDyPBbmq6PvvSUALZs5F3YaOU3baWKQrYq2lON4wIdYgpmHfQymnloLu9MS4p0QBhFrbiM94%2BJyE467QSHrPvquLQ0zY4JJzVn7x9kRj8gfyo07PPVOWg3WdB2l5%2BFcufVS4pZFFzqqva8vKoIRRnKDeDULbRZPK8AK8hWkxk%2Fk4HNf5ctY6U%2Bujx7KSP3PfvKZUdTgYYQlkEYy3HWtFbRrO%2BOCu8H3fuUlP%2B7YNqjqRw%3D%3D&questionId=q-ledger-agent-server&path=/",
    "https://exam.sanand.workers.dev/questionData?email=24f3004574%40ds.study.iitm.ac.in&quizSign=eGWqIkQ8msfMhMn7uVf5c8zK31EqJWmXMWhWdEDvrNcpN%2Fn90xG4BzKWIBNTeP749QvHW6GMXTf7AMYmCxsIQ12s21BYuZla90%2F6o9V01Ew39q2JPd4sOMgcjBjteGJOt8iCuGaHTFCJZdPVRKsCGegijoDSQtLYr86T5wIHlCqP8FZq49iaQT%2BokiK5Du%2FKa2OXi7rvVdrgy%2FTlCGRJhQtdxnWk6j0vACekpSBey5AhRykMX7b9K%2BcRZ8wDP2D08ig9Z8VT7ssZ4DMJ2amWQ%2BIwujOC2uQ9aPre5HOp7RZPBjcj3yUdSdq36wGpOnUl%2FR4tVdi4usJ3X2AMD7kmWA%3D%3D&questionId=q-ledger-agent-server&path=/",
] if u]

# Which timestamp decides the business month of an order. Switch to "updated_at" if refund-month
# questions come back wrong on boundary cases.
DATE_FIELD = os.environ.get("DATE_FIELD", "created_at")
REFUND_DATE_FIELD = os.environ.get("REFUND_DATE_FIELD", DATE_FIELD)

CACHE = {"t": 0.0, "orders": None, "rates": None}
CACHE_TTL = 600


def parse_ts(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(IST)


def build_orders(rows, rates):
    """Keep the latest updated_at row per order id, convert to USD, convert dates to IST."""
    best = {}
    for r in rows:
        try:
            upd = parse_ts(r["updated_at"])
        except Exception:
            continue
        cur = best.get(r["id"])
        if cur is None or upd >= cur[0]:
            best[r["id"]] = (upd, r)
    out = []
    for upd, r in best.values():
        cur = str(r.get("currency", "USD")).strip().upper()
        rate = rates.get(cur, 1.0)
        try:
            created = parse_ts(r["created_at"])
        except Exception:
            created = upd
        amt = float(r.get("amount") or 0) * rate
        out.append({
            "id": r["id"],
            "customer": str(r.get("customer", "")).strip(),
            "region": str(r.get("region", "")).strip(),
            "product": str(r.get("product", "")).strip(),
            "qty": int(r.get("qty") or 0),
            "usd": amt,
            "status": str(r.get("status", "")).strip().lower(),
            "created_at": created,
            "updated_at": upd,
        })
    return out


_LOAD_LOCK = None


async def load_data(force=False):
    global _LOAD_LOCK
    if not force and CACHE["orders"] is not None and time.time() - CACHE["t"] < CACHE_TTL:
        return CACHE["orders"]
    import asyncio
    if _LOAD_LOCK is None:
        _LOAD_LOCK = asyncio.Lock()
    async with _LOAD_LOCK:                       # concurrent first requests share one download
        if not force and CACHE["orders"] is not None and time.time() - CACHE["t"] < CACHE_TTL:
            return CACHE["orders"]
        return await _load_data_locked()


async def _load_data_locked():
    last_err = None
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as c:
        for url in LEDGER_URLS:
            try:
                base = url[:-len("path=/")] if url.endswith("path=/") else url
                rr = await c.get(base + "path=%2Frates")
                rr.raise_for_status()
                rates = {k.upper(): float(v) for k, v in rr.json()["usd_per_unit"].items()}
                er = await c.get(base + "path=%2Fexport")
                er.raise_for_status()
                rows = [json.loads(line) for line in er.text.splitlines() if line.strip()]
                if not rows:
                    raise ValueError("empty export")
                CACHE.update(t=time.time(), orders=build_orders(rows, rates), rates=rates)
                return CACHE["orders"]
            except Exception as e:           # try the next URL
                last_err = e
    if CACHE["orders"] is not None:           # stale data is better than nothing
        return CACHE["orders"]
    raise RuntimeError(f"could not load ledger: {last_err}")


# ---------------------------------------------------------------- question -> spec
MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
          "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
          "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
          "december": 12, "dec": 12}
MON = "|".join(sorted(MONTHS, key=len, reverse=True))
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MD_RE = re.compile(rf"\b({MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I)
DM_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MON})\.?,?\s+(\d{{4}})\b", re.I)
MY_RE = re.compile(rf"\b({MON})\b\.?(?:\s*,?\s*(\d{{4}}))?", re.I)
Q_RE = re.compile(r"\bq([1-4])\b(?:\s*,?\s*(\d{4}))?", re.I)
QW_RE = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\b(?:\s+(?:of\s+)?(\d{4}))?", re.I)
RANGE_WORDS = re.compile(r"\b(between|from|through|thru|until|till|to)\b|\s-\s|–|—", re.I)


def month_bounds(y, m):
    s = datetime(y, m, 1, tzinfo=IST)
    e = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=IST)
    return s, e


def day_bounds(d: date):
    s = datetime(d.year, d.month, d.day, tzinfo=IST)
    return s, s + timedelta(days=1)


def parse_time(q: str, default_year: int):
    """Return (start, end) with end exclusive, or None."""
    days = []                                  # (pos, date)
    used = []
    for m in ISO_RE.finditer(q):
        try:
            days.append((m.start(), date(int(m[1]), int(m[2]), int(m[3])))); used.append((m.start(), m.end()))
        except ValueError:
            pass
    for m in MD_RE.finditer(q):
        if any(a <= m.start() < b for a, b in used):
            continue
        mon = MONTHS[m[1].lower()]
        if m[1].lower() == "may" and not m[3] and not re.search(r"\b(in|on|during|of|from|to|and|between|since|until)\s+$", q[:m.start()], re.I):
            continue
        try:
            days.append((m.start(), date(int(m[3]) if m[3] else default_year, mon, int(m[2])))); used.append((m.start(), m.end()))
        except ValueError:
            pass
    for m in DM_RE.finditer(q):
        if any(a <= m.start() < b for a, b in used):
            continue
        try:
            days.append((m.start(), date(int(m[3]), MONTHS[m[2].lower()], int(m[1])))); used.append((m.start(), m.end()))
        except ValueError:
            pass
    days.sort()
    if len(days) >= 2:
        a, b = days[0][1], days[1][1]
        if a > b:
            a, b = b, a
        return day_bounds(a)[0], day_bounds(b)[1]
    if len(days) == 1:
        return day_bounds(days[0][1])
    m = Q_RE.search(q)
    if m:
        qn, y = int(m[1]), int(m[2]) if m[2] else default_year
        return month_bounds(y, 3 * qn - 2)[0], month_bounds(y, 3 * qn)[1]
    m = QW_RE.search(q)
    if m:
        qn = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}[m[1].lower()]
        y = int(m[2]) if m[2] else default_year
        return month_bounds(y, 3 * qn - 2)[0], month_bounds(y, 3 * qn)[1]
    mons = []
    for m in MY_RE.finditer(q):
        if m[1].lower() == "may" and not m[2] and not re.search(r"\b(in|during|of|from|to|and|between|since|until|for)\s+$", q[:m.start()], re.I):
            continue
        mons.append((m.start(), MONTHS[m[1].lower()], int(m[2]) if m[2] else None))
    if mons:
        if len(mons) >= 2 and RANGE_WORDS.search(q[mons[0][0]:mons[1][0] + 1] + " " + q[:mons[0][0]][-12:]):
            (_, m1, y1), (_, m2, y2) = mons[0], mons[1]
            y2 = y2 or y1 or default_year
            y1 = y1 or (y2 if m1 <= m2 else y2 - 1)
            return month_bounds(y1, m1)[0], month_bounds(y2, m2)[1]
        _, mo, y = mons[0]
        return month_bounds(y or default_year, mo)
    m = re.search(r"\b(?:in|during|for|of|throughout)\s+(?:the\s+year\s+)?(20\d{2})\b|\b(20\d{2})\b", q)
    if m:
        y = int(m[1] or m[2])
        return datetime(y, 1, 1, tzinfo=IST), datetime(y + 1, 1, 1, tzinfo=IST)
    return None


def find_mentions(q, values):
    """Longest-first, case-insensitive, optional plural 's', word boundaries."""
    ql = q.lower()
    hits = []
    for v in sorted({x for x in values if x}, key=len, reverse=True):
        pat = r"(?<![A-Za-z0-9])" + re.escape(v.lower()) + r"(?:'?s|es)?(?![A-Za-z0-9])"
        for m in re.finditer(pat, ql):
            if not any(not (m.end() <= a or m.start() >= b) for a, b, _ in hits):
                hits.append((m.start(), m.end(), v))
    return [v for _, _, v in sorted(hits)]


def has(q, *pats):
    return any(re.search(p, q, re.I) for p in pats)


def make_spec(q: str, orders):
    regions = {o["region"] for o in orders}
    products = {o["product"] for o in orders}
    customers = {o["customer"] for o in orders}
    statuses = {o["status"] for o in orders}
    years = [o["created_at"].year for o in orders]
    default_year = max(set(years), key=years.count) if years else 2026

    spec = {"region": None, "product": None, "customer": None, "status": None,
            "range": parse_time(q, default_year), "group": None, "top": None, "metric": None}

    # entities
    cust = re.findall(r"\bC\d{3,6}\b", q, re.I)
    spec["customer"] = (find_mentions(q, customers) or [c.upper() for c in cust] or [None])[0]
    prods = find_mentions(q, products)
    regs = find_mentions(q, regions)
    spec["product"] = prods[0] if prods else None
    spec["region"] = regs[0] if regs else None

    # grouping / ranking
    gm = re.search(r"\b(which|what|who|whom|top|best|highest|most|largest|biggest|lowest|least|worst|smallest)\b(?:\s+\w+){0,3}?\s+(region|product|customer|client|buyer)s?\b", q, re.I)
    if gm:
        spec["group"] = {"client": "customer", "buyer": "customer"}.get(gm[2].lower(), gm[2].lower())
    elif re.search(r"\b(who)\b", q, re.I):
        spec["group"] = "customer"
    if spec["group"]:
        tm = re.search(r"\b(?:top|best|bottom|worst)\s+(\d+)\b", q, re.I)
        spec["top"] = int(tm[1]) if tm else None
        spec["order"] = "asc" if re.search(r"\b(lowest|least|worst|smallest|bottom|fewest)\b", q, re.I) else "desc"
        if spec["group"] == "region" and spec["region"] and not re.search(r"\b(other|than|besides|except)\b", q, re.I):
            pass

    # status filter
    refund_q = has(q, r"\brefund")
    for s in sorted(statuses, key=len, reverse=True):
        if s and re.search(rf"\b{re.escape(s)}\b", q, re.I):
            spec["status"] = s
            break
    if refund_q and "refunded" in statuses:
        spec["status"] = "refunded"

    # metric
    if has(q, r"\b(rate|percent|percentage|proportion|share|ratio)\b", r"%"):
        spec["metric"] = "rate"
    elif has(q, r"\b(average|avg|mean|aov)\b"):
        spec["metric"] = "avg"
    elif has(q, r"\b(unique|distinct|different)\s+customers?\b", r"\bhow many\s+(?:\w+\s+){0,2}customers\b", r"\bnumber of\s+(?:\w+\s+){0,2}customers\b"):
        spec["metric"] = "customers"
    elif has(q, r"\b(units?|quantity|quantities|pieces|items)\b", r"\bhow many\s+(?:\w+\s+){0,3}(?:were\s+)?sold\b"):
        spec["metric"] = "units"
    elif has(q, r"\bhow many\b", r"\bnumber of\b", r"\bcount\b", r"\btotal orders\b") and has(q, r"\borders?\b|\brefunds?\b|\brefunded\b"):
        spec["metric"] = "count"
    elif refund_q and has(q, r"\bhow much\b", r"\bvalue\b", r"\bamount\b", r"\bworth\b", r"\busd\b", r"\btotal\b", r"\bsum\b", r"\$"):
        spec["metric"] = "refund_total"
    elif has(q, r"\brevenue\b", r"\bsales\b", r"\bearn", r"\bgross\b", r"\bturnover\b", r"\bspent\b|\bspend\b", r"\bgenerat", r"\bhow much\b", r"\bincome\b"):
        spec["metric"] = "revenue"
    elif refund_q:
        spec["metric"] = "count"
    else:
        spec["metric"] = "revenue"
    if spec["group"] and spec["metric"] in ("avg", "customers", "rate"):
        pass
    if spec["group"] and spec["metric"] == "count" and not has(q, r"\bhow many\b", r"\bnumber of\b"):
        spec["metric"] = "count"
    return spec


# ---------------------------------------------------------------- spec -> answer
def in_range(o, spec, field):
    r = spec["range"]
    if not r:
        return True
    t = o[field]
    return r[0] <= t < r[1]


def select(orders, spec, status):
    out = []
    for o in orders:
        if spec["region"] and o["region"].lower() != spec["region"].lower() and not spec.get("_group_is_region"):
            continue
        if spec["product"] and o["product"].lower() != spec["product"].lower() and not spec.get("_group_is_product"):
            continue
        if spec["customer"] and o["customer"].lower() != spec["customer"].lower() and not spec.get("_group_is_customer"):
            continue
        if status and o["status"] != status:
            continue
        field = REFUND_DATE_FIELD if o["status"] == "refunded" else DATE_FIELD
        if not in_range(o, spec, field):
            continue
        out.append(o)
    return out


def money(x):
    return round(x + 1e-9, 2)


def measure(rows, metric):
    if metric == "revenue" or metric == "refund_total":
        return sum(o["usd"] for o in rows)
    if metric == "units":
        return sum(o["qty"] for o in rows)
    if metric == "customers":
        return len({o["customer"] for o in rows})
    return len(rows)


def run_spec(spec, orders):
    metric = spec["metric"]
    if metric in ("revenue", "units", "avg"):
        status = spec["status"] or "paid"
    elif metric == "refund_total":
        status = "refunded"
    elif metric == "customers":
        status = spec["status"] or "paid"
    else:
        status = spec["status"]
    grp = spec.get("group")
    # a grouping dimension that is also given as a filter value (e.g. "North region ... which product") is fine;
    # a dimension we group by is never filtered
    if grp:
        spec = dict(spec); spec[f"_group_is_{grp}"] = True
        rows = select(orders, spec, status)
        buckets = defaultdict(list)
        for o in rows:
            buckets[o[grp]].append(o)
        mm = metric if metric not in ("avg", "rate") else "revenue"
        scored = [(k, measure(v, mm)) for k, v in buckets.items()]
        if not scored:
            return None
        rev = spec.get("order", "desc") == "desc"
        scored.sort(key=lambda kv: (-kv[1] if rev else kv[1], kv[0]))
        if spec.get("top"):
            return [k for k, _ in scored[:spec["top"]]]
        return scored[0][0]
    if metric == "rate":
        base = select(orders, dict(spec), None)
        part = [o for o in base if o["status"] == (spec["status"] or "refunded")]
        return round(100.0 * len(part) / len(base), 2) if base else 0
    rows = select(orders, spec, status)
    if metric == "avg":
        return money(sum(o["usd"] for o in rows) / len(rows)) if rows else 0
    val = measure(rows, metric)
    return money(val) if metric in ("revenue", "refund_total") else int(val)


async def llm_spec(q, orders):
    """Optional fallback: let an LLM turn the question into the same spec (computation stays in code)."""
    token = os.environ.get("AIPIPE_TOKEN") or os.environ.get("OPENAI_API_KEY")
    if not token:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://aipipe.org/openai/v1")
    model = os.environ.get("LLM_MODEL", "gpt-4.1-mini")
    sysmsg = ("Convert the question into JSON with keys: metric (revenue|refund_total|count|units|customers|avg|rate), "
              "region, product, customer, status (paid|refunded|null), start, end (YYYY-MM-DD, end exclusive, null if none), "
              "group (region|product|customer|null), top (int|null), order (asc|desc). Business dates are Asia/Kolkata. "
              "Reply with JSON only. Regions: %s. Products: %s." % (sorted({o['region'] for o in orders}), sorted({o['product'] for o in orders})))
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(base + "/chat/completions", headers={"Authorization": f"Bearer {token}"},
                         json={"model": model, "temperature": 0, "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": q}]})
        txt = r.json()["choices"][0]["message"]["content"]
    d = json.loads(re.search(r"\{.*\}", txt, re.S)[0])
    rng = None
    if d.get("start") and d.get("end"):
        rng = (datetime.fromisoformat(d["start"]).replace(tzinfo=IST), datetime.fromisoformat(d["end"]).replace(tzinfo=IST))
    return {"region": d.get("region"), "product": d.get("product"), "customer": d.get("customer"), "status": d.get("status"),
            "range": rng, "group": d.get("group"), "top": d.get("top"), "order": d.get("order") or "desc", "metric": d.get("metric") or "revenue"}


async def answer_question(q: str):
    orders = await load_data()
    spec = make_spec(q, orders)
    try:
        return run_spec(spec, orders), spec
    except Exception:
        s2 = await llm_spec(q, orders)
        if s2:
            return run_spec(s2, orders), s2
        raise


def spec_json(spec):
    s = dict(spec)
    if s.get("range"):
        s["range"] = [s["range"][0].isoformat(), s["range"][1].isoformat()]
    return {k: v for k, v in s.items() if not k.startswith("_")}


@app.post("/ask")
async def ask(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    q = (body.get("question") or body.get("q") or "").strip()
    try:
        ans, _ = await answer_question(q)
        return {"answer": ans}
    except Exception as e:
        return JSONResponse({"answer": None, "error": str(e)}, status_code=200)


@app.get("/ask")
async def ask_get(question: str = ""):
    """Debug helper: shows how a question was understood. Open /ask?question=..."""
    ans, spec = await answer_question(question)
    return {"answer": ans, "understood_as": spec_json(spec)}

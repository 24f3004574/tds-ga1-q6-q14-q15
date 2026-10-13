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


# ---------------------------------------------------------------- Q15 (to be filled in)
@app.post("/ask")
async def ask(request: Request):
    body = await request.json()
    return {"answer": None, "note": "not implemented yet", "question": body.get("question")}

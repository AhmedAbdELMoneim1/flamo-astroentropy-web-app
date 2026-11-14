"""
flamo token + catalog server (FastAPI).

For data-packet transport the Backend does NOT send or receive LiveKit packets.
It only:
  1. Issues LiveKit JWTs (with agent dispatch)
  2. Serves domain data: GET /api/mission, and GET /api/categories (the catalog of
     pillars, views, scenarios and input conditions; the path name is historical)

No special grant is required for client-side publishData — room_join is enough.
"""

import hmac
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from livekit import api
from pydantic import BaseModel

from src import flameo, rag
from src.charts import build_o2_vs_pressure
from src.docs import local_pdf
from src.categories import load_coverage, public_catalog

load_dotenv(".env.local")
load_dotenv(".env")

LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

AGENT_NAME = os.getenv("AGENT_NAME", "nasa-agent")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

# serving.db is required: the catalog carries the coverage levels and the O2-vs-pressure chart is built from it once.
flameo.init()
load_coverage(flameo.call)
O2_VS_PRESSURE = build_o2_vs_pressure(flameo.call)

app = FastAPI(title="flamo token server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    identity: str | None = None
    name: str | None = None
    room: str | None = None


class TokenResponse(BaseModel):
    server_url: str
    participant_token: str
    room: str
    identity: str


class RagAsk(BaseModel):
    question: str
    params: dict = {}


@app.post("/api/internal/rag/ask")
async def internal_rag_ask(req: RagAsk, x_internal_key: str | None = Header(default=None)):
    """For the deployed agent only (it has no Postgres): the same scoped RAG, behind a shared secret. Off (404) when RAG_INTERNAL_KEY is not set."""
    key = os.getenv("RAG_INTERNAL_KEY", "")
    if not key:
        raise HTTPException(status_code=404)
    if not hmac.compare_digest(x_internal_key or "", key):
        raise HTTPException(status_code=403)
    if not rag.available() or rag.remote_url():
        raise HTTPException(status_code=503, detail="RAG is off")
    return await rag.get().ask(req.question[:500], **{k: v for k, v in req.params.items() if k in ("o2_pct", "pressure_kpa", "material", "fuel", "psi", "pillar", "scenario")})


@app.get("/health")
def health():
    return {"ok": True, "rag": rag.available() and not rag.remote_url()}


@app.post("/api/token", response_model=TokenResponse)
def create_token(req: TokenRequest):
    if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        raise HTTPException(500, "LiveKit env vars are not configured")

    room = req.room or f"room-{uuid.uuid4().hex[:8]}"
    identity = req.identity or f"user-{uuid.uuid4().hex[:8]}"

    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(req.name or identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                # Optional: only needed if you also use setAttributes / setMetadata
                # can_update_own_metadata=True,
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)]
            )
        )
        .to_jwt()
    )

    return TokenResponse(
        server_url=os.getenv("LIVEKIT_PUBLIC_URL") or LIVEKIT_URL,      # browser address (wss://your-domain) can differ from the one the agent uses inside Docker
        participant_token=token,
        room=room,
        identity=identity,
    )


def fetch_from_upstream() -> dict:
    # TODO: replace with a real call to your upstream service / DB
    return {
        "mission": "Artemis Demo",
        "destination": "Moon",
        "crew_size": 4,
        "launch_date": "2027-03-14",
    }


@app.get("/api/mission")
def get_mission():
    return fetch_from_upstream()


@app.get("/api/categories")
def get_categories():
    """Catalog: pillars, views, scenarios + input specs; single source of truth shared with the agent."""
    return public_catalog()


@app.get("/api/charts/o2_vs_pressure")
def get_o2_vs_pressure(investigation: str | None = None, scenario: str | None = None):
    """The full tested oxygen-against-pressure scatter (all series and points) with the scenario points, as flameo built it.
    It does not depend on the question; answers and views point to it with a chart `ref`.
    Optional filters: `investigation` (a PSI code like PSI-20 or part of its name) keeps that investigation's series; `scenario`
    (iss, moon_base, spacesuit, exploration_10_2, exploration_8_2) flags its cross point `selected`. No filter = the unchanged chart."""
    from src.charts import filter_o2_vs_pressure
    return filter_o2_vs_pressure(O2_VS_PRESSURE, investigation, scenario)


@app.get("/api/nearest")
def get_nearest(o2: float, p: float, material: str | None = None, source: str | None = None, investigation: str | None = None):
    """Your conditions: what the PSI tests say near this oxygen (percent) and pressure (psi). One SQL pass, no model call, so a slider move costs nothing.
    The values are clamped to the slider ranges. The answer is flameo's `nearest_tests`, trimmed (counts, rows, partial pressure with its formula, scenario and source markers)."""
    from src import adapter
    from src.categories import normalize_conditions
    c = normalize_conditions({"oxygen_pct": o2, "pressure_psi": p})
    if "oxygen_pct" not in c or "pressure_psi" not in c:
        raise HTTPException(422, "bad conditions")
    a = flameo.call("nearest_tests", o2_pct=c["oxygen_pct"], pressure_psi=max(c["pressure_psi"], 0.1), **({"material": material} if material else {}))
    if a.get("status") == "unknown" or "conditions" not in a:
        raise HTTPException(422, "no conditions")
    out = adapter.to_conditions(a, source)
    out["tolerance"] = flameo.tolerance()               # what "near" means (flameo's config), so the map can draw it
    if investigation:                                   # optional narrowing to one investigation: the counts stay flameo's, the lists are cut
        from src.charts import investigation_matches
        w = investigation.strip().lower()
        if w == "burner":                                # burner-stream tests are not atmosphere tests: nothing of them is in these lists
            keep = lambda name: False
        elif w == "other":                               # every investigation that is not one of the five named series on the map
            import re
            named = [m.group(1) for x in O2_VS_PRESSURE["series"] if (m := re.search(r"\((PSI-\d+)\)", x["name"]))]
            keep = lambda name: not any(n and n.lower() in (name or "").lower() for n in named)
        else:
            keep = lambda name: investigation_matches(name, investigation)
        out["spread_points"] = [x for x in out["spread_points"] if keep(x.get("investigation"))]
        out["rows"] = [r for r in out["rows"] if keep(r.get("investigation"))]
        out["filter"] = {"investigation": investigation, "rows_shown": len(out["rows"]), "spread_shown": len(out["spread_points"])}
    return out


@app.get("/api/docs/{doc_id}")
def get_document(doc_id: str):
    """A NASA PSI document (a source of an answer) from its local copy; the viewer opens it at the cited page (#page=N).
    The file is found through the serving.db `source` table, never through a path in the request. Papers are not served (DOI link only)."""
    p = local_pdf(doc_id)
    if p is None:
        raise HTTPException(404, "no such document")
    return FileResponse(p, media_type="application/pdf", headers={"Content-Disposition": "inline"})

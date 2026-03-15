from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.api.routes_scenarios import router as scenarios_router
from app.api.routes_game import router as game_router, _llm
from app.engines.llm_router import LLMConfig, LLMProvider

app = FastAPI(title="Project Lunar", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scenarios_router, prefix="/api/scenarios", tags=["scenarios"])
app.include_router(game_router, prefix="/api/game", tags=["game"])


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/health/neo4j")
async def health_neo4j():
    uri = settings.neo4j_uri
    user = settings.neo4j_user
    password = settings.neo4j_password
    try:
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}


class SettingsUpdateRequest(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    temperature: float = 0.8
    max_tokens: int = 2000


@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    try:
        provider = LLMProvider(req.provider)
    except ValueError:
        provider = LLMProvider.DEEPSEEK
    _llm.config = LLMConfig(
        primary_provider=provider,
        primary_model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    return {"status": "ok", "provider": provider.value, "model": req.model}


@app.get("/api/settings")
def get_settings():
    return {
        "provider": _llm.config.primary_provider.value,
        "model": _llm.config.primary_model,
        "temperature": _llm.config.temperature,
        "max_tokens": _llm.config.max_tokens,
    }

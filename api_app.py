from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from achievement_window_service import generate_achievement_window


class AchievementWindowRequest(BaseModel):
    since: str
    until: str


app = FastAPI(title="dev-memory")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/achievement-window")
async def achievement_window(payload: AchievementWindowRequest) -> JSONResponse:
    try:
        data = await generate_achievement_window(since=payload.since, until=payload.until)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(content=data)

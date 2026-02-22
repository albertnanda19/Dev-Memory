from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from achievement_window_service import generate_achievement_window_markdown


class AchievementWindowRequest(BaseModel):
    since: str
    until: str


app = FastAPI(title="dev-memory")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/achievement-window", response_class=PlainTextResponse)
async def achievement_window(payload: AchievementWindowRequest) -> PlainTextResponse:
    try:
        text = await generate_achievement_window_markdown(since=payload.since, until=payload.until)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PlainTextResponse(content=text, media_type="text/markdown; charset=utf-8")

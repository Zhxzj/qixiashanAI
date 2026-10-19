"""Bounded local APIs for explicit annotation preview/save/reset."""
import json
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictFloat
from app.services.map_annotations import AnnotationConflict


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=96)
    coord: list[StrictFloat] = Field(min_length=2, max_length=2)
    revision: int = Field(ge=0, strict=True)


class SavePosition(Position):
    expires: int = Field(strict=True)
    preview_token: str = Field(min_length=64, max_length=64)


class ResetPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=96)
    revision: int = Field(ge=0, strict=True)


async def bounded(request: Request):
    if request.method == "POST":
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "仅接受JSON")
        if len(await request.body()) > 4096:
            raise HTTPException(413, "标注请求过大")


def router(store):
    api = APIRouter(prefix="/api/map/annotations", dependencies=[Depends(bounded)])

    def invoke(fn, *args):
        try:
            return fn(*args)
        except AnnotationConflict as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except OSError:
            raise HTTPException(500, "位置保存或导出失败，原数据仍保留，请重试")

    @api.get("")
    async def get():
        return store.snapshot()

    @api.post("/preview")
    async def preview(body: Position):
        return invoke(store.preview, body.id, body.coord, body.revision)

    @api.post("/save")
    async def save(body: SavePosition):
        return invoke(store.save, body.id, body.coord, body.revision, body.expires, body.preview_token)

    @api.post("/reset")
    async def reset(body: ResetPosition):
        return invoke(store.reset, body.id, body.revision)

    @api.get("/export")
    async def export():
        data = invoke(store.export)
        return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="map-annotations-backup.json"'})
    return api

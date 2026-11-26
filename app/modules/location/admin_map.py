"""God's view: the admin dashboard's map of people and places (decision D.8).

Admins only. Two reads, both of what the database already holds:

- **Hexagons:** `cell_activity`'s counts per H3 cell (people living there, active
  people, recent posts) at resolution 8, 7 or 6, with each cell's outline. Counts
  are exact, as the product owner chose, so every opening of the map is audited,
  at most once an hour per admin.
- **Places:** the named places "near X" comes from (decision L.4), as GeoJSON
  with their boundaries simplified to about 10 m.

Never a person, an account or a coordinate of anyone: a cell's outline is a
fixed hexagon, the same for everyone who lives in it.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Final

import h3
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionDep
from app.core.errors import BadRequestError
from app.core.redis import CACHE_ERRORS, get_redis
from app.modules.location.models import CellActivity
from app.modules.moderation.audit import record_audit_event
from app.modules.moderation.models import AuditAction, AuditActorType
from app.modules.staff.dependencies import AdminStaff
from app.modules.staff.models import StaffAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/map", tags=["admin: map"])
RedisDep = Annotated[Redis, Depends(get_redis)]

MAX_CELLS: Final = 20_000
AUDIT_EVERY_SECONDS: Final = 3600


class BoundingBox(BaseModel):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    def contains(self, latitude: float, longitude: float) -> bool:
        return self.south <= latitude <= self.north and self.west <= longitude <= self.east


def bounding_box(
    west: Annotated[float | None, Query(ge=-180, le=180)] = None,
    south: Annotated[float | None, Query(ge=-90, le=90)] = None,
    east: Annotated[float | None, Query(ge=-180, le=180)] = None,
    north: Annotated[float | None, Query(ge=-90, le=90)] = None,
) -> BoundingBox | None:
    given = [value is not None for value in (west, south, east, north)]
    if not any(given):
        return None
    if not all(given):
        raise BadRequestError("Give all four of west, south, east and north, or none")
    box = BoundingBox(west=west, south=south, east=east, north=north)
    if box.west > box.east or box.south > box.north:
        raise BadRequestError("The box's west must be less than east, and south than north")
    return box


BoxDep = Annotated[BoundingBox | None, Depends(bounding_box)]


class MapCellOut(BaseModel):
    id: str = Field(description="The H3 cell, as its usual hexadecimal string.")
    people: int = Field(description="Everyone whose home is in the cell.")
    active: int = Field(description="Of them, in good standing and active in the last 14 days.")
    recent_posts: int = Field(description="Counted recent posts made in the cell (decision T.2).")
    boundary: list[tuple[float, float]] = Field(description="The hexagon's corners, [lat, lng].")


class MapCellsOut(BaseModel):
    resolution: int = Field(description="8, 7 or 6.")
    cells: list[MapCellOut]
    truncated: bool = Field(description="More cells matched than the 20,000 returned.")
    people: int = Field(description="People in the cells returned.")


async def _audit_view(
    session: AsyncSession, redis: Redis, staff: StaffAccount, resolution: int
) -> None:
    """At most once an hour per admin: a map is opened, panned and zoomed many
    times over. If Redis can't say, it records anyway: better twice than never."""
    try:
        first = await redis.set(
            f"audit:people-map:{staff.id}", "1", nx=True, ex=AUDIT_EVERY_SECONDS
        )
    except CACHE_ERRORS:
        logger.warning("people_map_audit_dedupe_unavailable", exc_info=True)
        first = True
    if first:
        await record_audit_event(
            session,
            action=AuditAction.people_map_viewed,
            actor_type=AuditActorType.moderator,
            actor_id=staff.id,
            context={"resolution": resolution},
        )


@router.get(
    "/cells",
    response_model=MapCellsOut,
    summary="People per hexagon (admin)",
    description=(
        "God's view (decision D.8): `cell_activity`'s exact counts per H3 cell at "
        "resolution 8 (~0.7 km²), 7 (~5 km²) or 6 (~36 km²), with each cell's outline. "
        "Optionally only cells whose centre is in a box. Opening the map is audited, "
        "at most once an hour per admin."
    ),
)
async def map_cells(
    admin: AdminStaff,
    session: SessionDep,
    redis: RedisDep,
    box: BoxDep,
    resolution: Annotated[int, Query(ge=6, le=8, description="8, 7 or 6.")] = 8,
) -> MapCellsOut:
    rows = (
        await session.execute(
            select(
                CellActivity.cell,
                CellActivity.registered_user_count,
                CellActivity.active_user_count,
                CellActivity.recent_post_count,
            ).where(
                CellActivity.resolution == resolution,
                or_(
                    CellActivity.registered_user_count > 0,
                    CellActivity.recent_post_count > 0,
                ),
            )
        )
    ).all()

    cells: list[MapCellOut] = []
    truncated = False
    for cell, people, active, posts in rows:
        name = h3.int_to_str(int(cell))
        if box is not None and not box.contains(*h3.cell_to_latlng(name)):
            continue
        if len(cells) >= MAX_CELLS:
            truncated = True
            break
        cells.append(
            MapCellOut(
                id=name,
                people=int(people),
                active=int(active),
                recent_posts=int(posts),
                boundary=[(round(lat, 6), round(lng, 6)) for lat, lng in h3.cell_to_boundary(name)],
            )
        )
    await _audit_view(session, redis, admin, resolution)
    return MapCellsOut(
        resolution=resolution,
        cells=cells,
        truncated=truncated,
        people=sum(cell.people for cell in cells),
    )


# Simplified to about 10 m (0.0001°): plenty for a map, a fraction of the points.
_PLACES_SQL: Final = """
SELECT
    name, level, ward, sub_county, county,
    ST_AsGeoJSON(ST_SimplifyPreserveTopology(boundary::geometry, 0.0001), 6) AS geometry,
    ST_Y(ST_PointOnSurface(boundary::geometry)) AS label_lat,
    ST_X(ST_PointOnSurface(boundary::geometry)) AS label_lng
FROM places
{where}
ORDER BY CASE level WHEN 'ward' THEN 0 WHEN 'town' THEN 1 WHEN 'sublocation' THEN 2 ELSE 3 END, name
"""


@router.get(
    "/places",
    summary="Named places and their boundaries (admin)",
    description=(
        'God\'s view (decision D.8): the places "near X" comes from (decision L.4), as '
        "a GeoJSON FeatureCollection with name, level, ward, sub-county, county and "
        "a point to put the label. Optionally only places touching a box."
    ),
    response_model=dict[str, Any],
)
async def map_places(admin: AdminStaff, session: SessionDep, box: BoxDep) -> dict[str, Any]:
    where = ""
    params: dict[str, float] = {}
    if box is not None:
        where = "WHERE ST_Intersects(boundary::geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))"
        params = {"w": box.west, "s": box.south, "e": box.east, "n": box.north}
    statement = text(_PLACES_SQL.format(where=where))
    rows = (await session.execute(statement, params)).all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(row.geometry),
                "properties": {
                    "name": row.name,
                    "level": row.level,
                    "ward": row.ward,
                    "sub_county": row.sub_county,
                    "county": row.county,
                    "label_at": [round(row.label_lat, 6), round(row.label_lng, 6)],
                },
            }
            for row in rows
        ],
    }

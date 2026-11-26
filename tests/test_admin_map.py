"""God's view (decision D.8): people per hexagon and named places, for admins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import h3
import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.location import cells
from app.modules.moderation.models import AuditAction, AuditEvent
from app.modules.staff.credentials import create_staff_token
from app.modules.staff.models import StaffRole, StaffSession
from tests.factories import KARATINA, NYERI_TOWN, make_staff, set_cell_density
from tests.test_places import _feature, _seed


async def admin_headers(session: AsyncSession, settings: Settings) -> dict[str, str]:
    staff_id = (await make_staff(session, role=StaffRole.admin)).account.id
    staff_session = StaffSession(
        staff_id=staff_id, expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    session.add(staff_session)
    await session.flush()
    token = create_staff_token(
        staff_id=staff_id,
        session_id=staff_session.id,
        expires_at=staff_session.expires_at,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_cells_carry_their_counts_and_outline(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    await set_cell_density(
        db_session,
        origin=NYERI_TOWN,
        active_per_cell=3,
        registered_per_cell=5,
        posts_per_cell=2,
        rings=1,
    )
    headers = await admin_headers(db_session, settings)

    body = (await client.get("/v1/admin/map/cells", headers=headers)).json()

    assert body["resolution"] == 8
    assert len(body["cells"]) == 7
    assert body["people"] == 35
    assert body["truncated"] is False
    home = h3.int_to_str(cells.locate(*NYERI_TOWN.as_tuple()).cell_res8)
    cell = next(c for c in body["cells"] if c["id"] == home)
    assert (cell["people"], cell["active"], cell["recent_posts"]) == (5, 3, 2)
    assert len(cell["boundary"]) == 6
    for lat, lng in cell["boundary"]:
        assert abs(lat - NYERI_TOWN.latitude) < 0.02 and abs(lng - NYERI_TOWN.longitude) < 0.02


async def test_cells_can_be_limited_to_a_box_and_a_resolution(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    await set_cell_density(db_session, origin=NYERI_TOWN, active_per_cell=1, rings=0)
    await set_cell_density(db_session, origin=KARATINA, active_per_cell=1, rings=0)
    await set_cell_density(db_session, origin=KARATINA, active_per_cell=4, rings=0, resolution=7)
    headers = await admin_headers(db_session, settings)
    around_nyeri = {"west": 36.9, "south": -0.5, "east": 37.0, "north": -0.35}

    boxed = (await client.get("/v1/admin/map/cells", headers=headers, params=around_nyeri)).json()
    assert [c["id"] for c in boxed["cells"]] == [
        h3.int_to_str(cells.locate(*NYERI_TOWN.as_tuple()).cell_res8)
    ]

    coarse = (
        await client.get("/v1/admin/map/cells", headers=headers, params={"resolution": 7})
    ).json()
    assert [c["people"] for c in coarse["cells"]] == [4]

    half = await client.get("/v1/admin/map/cells", headers=headers, params={"west": 36.9})
    assert half.status_code == 400
    assert (
        await client.get("/v1/admin/map/cells", headers=headers, params={"resolution": 9})
    ).status_code == 422


async def test_opening_the_map_is_audited_once_an_hour(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    headers = await admin_headers(db_session, settings)
    for resolution in (6, 7, 8, 8):
        assert (
            await client.get(
                "/v1/admin/map/cells", headers=headers, params={"resolution": resolution}
            )
        ).status_code == 200

    views = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == AuditAction.people_map_viewed)
            )
        )
        .scalars()
        .all()
    )
    assert len(views) == 1
    assert views[0].context == {"resolution": 6}
    # Places carry no counts of people, so they aren't audited.
    await client.get("/v1/admin/map/places", headers=headers)
    assert (
        await db_session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == AuditAction.people_map_viewed
            )
        )
    ) == 1


async def test_places_come_as_geojson_with_their_names(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    await _seed(
        db_session,
        _feature("Gatitu", NYERI_TOWN),
        _feature("Ruring'u", NYERI_TOWN, width_km=8.0, level="ward"),
        _feature("Karatina", KARATINA, level="town", county="Nyeri"),
    )
    headers = await admin_headers(db_session, settings)

    everything = (await client.get("/v1/admin/map/places", headers=headers)).json()
    assert everything["type"] == "FeatureCollection"
    names = [f["properties"]["name"] for f in everything["features"]]
    # Wards first, then towns, then the rest: the order a map labels them in.
    assert names == ["Ruring'u", "Karatina", "Gatitu"]
    gatitu = everything["features"][2]
    assert gatitu["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    lat, lng = gatitu["properties"]["label_at"]
    assert abs(lat - NYERI_TOWN.latitude) < 0.02 and abs(lng - NYERI_TOWN.longitude) < 0.02

    near_nyeri = {"west": 36.9, "south": -0.5, "east": 37.0, "north": -0.35}
    boxed = (await client.get("/v1/admin/map/places", headers=headers, params=near_nyeri)).json()
    assert sorted(f["properties"]["name"] for f in boxed["features"]) == ["Gatitu", "Ruring'u"]


async def test_a_moderator_gets_no_map(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    staff_id = (await make_staff(db_session)).account.id
    staff_session = StaffSession(
        staff_id=staff_id, expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    db_session.add(staff_session)
    await db_session.flush()
    token = create_staff_token(
        staff_id=staff_id,
        session_id=staff_session.id,
        expires_at=staff_session.expires_at,
        settings=settings,
    )
    for path in ("/v1/admin/map/cells", "/v1/admin/map/places"):
        response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, path
    assert uuid.UUID(str(staff_id))

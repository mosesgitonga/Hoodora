"""Named places, and "near Gatitu" on Home (decision L.4).

A place is named only to the person standing in it, from their phone's cell, and
never stored against them. The polygons here are synthetic squares, loaded
through the seed script so its geometry handling is tested on the way.
"""

from __future__ import annotations

import math
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.location import cells
from app.modules.location import service as location_service
from app.modules.location.models import Place
from scripts.seed_places import SeedError, SeedPlace, load_places, parse_places
from tests.factories import KARATINA, NYERI_TOWN, Coordinates

_METRES_PER_DEGREE = 111_320.0


def _square(centre: Coordinates, width_km: float) -> dict[str, Any]:
    """A GeoJSON Polygon, a square around a point."""
    half_lat = width_km * 500.0 / _METRES_PER_DEGREE
    half_lon = width_km * 500.0 / (_METRES_PER_DEGREE * math.cos(math.radians(centre.latitude)))
    west, east = centre.longitude - half_lon, centre.longitude + half_lon
    south, north = centre.latitude - half_lat, centre.latitude + half_lat
    return {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }


def _feature(
    name: str,
    centre: Coordinates,
    *,
    width_km: float = 2.0,
    level: str = "village",
    county: str = "Nyeri",
    source: str = "osm",
    multi: bool = False,
) -> dict[str, Any]:
    geometry = _square(centre, width_km)
    if multi:
        geometry = {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}
    return {
        "type": "Feature",
        "properties": {
            "name": name,
            "level": level,
            "ward": "Ruring'u",
            "sub_county": "Nyeri Central",
            "county": county,
            "source": source,
            "confidence": "generated cell",
        },
        "geometry": geometry,
    }


def _collection(*features: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


async def _seed(session: AsyncSession, *features: dict[str, Any]) -> None:
    await load_places(session, parse_places(_collection(*features), exclude_sources=frozenset()))


# ---------------------------------------------------------------------------
# Finding the place
# ---------------------------------------------------------------------------
async def test_the_place_covering_the_cell_is_named(db_session: AsyncSession) -> None:
    await _seed(db_session, _feature("Gatitu", NYERI_TOWN))

    near = await location_service.place_near(
        db_session, cell_res9=cells.to_cell(NYERI_TOWN.latitude, NYERI_TOWN.longitude, 9)
    )

    assert near == location_service.NearPlace(name="Gatitu", level="village", ward="Ruring'u")


async def test_outside_every_place_there_is_no_name(db_session: AsyncSession) -> None:
    """Normal before a county is seeded, so it must not be an error."""
    await _seed(db_session, _feature("Gatitu", NYERI_TOWN))

    near = await location_service.place_near(
        db_session, cell_res9=cells.to_cell(KARATINA.latitude, KARATINA.longitude, 9)
    )

    assert near is None


async def test_the_smaller_of_two_overlapping_places_wins(db_session: AsyncSession) -> None:
    """Seeds should not overlap, but if a ward and a village ever both cover a
    spot, the village says more."""
    await _seed(
        db_session,
        _feature("Ruring'u", NYERI_TOWN, width_km=8.0, level="ward"),
        _feature("Gatitu", NYERI_TOWN, width_km=1.5),
    )

    near = await location_service.place_near(
        db_session, cell_res9=cells.to_cell(NYERI_TOWN.latitude, NYERI_TOWN.longitude, 9)
    )

    assert near is not None
    assert near.name == "Gatitu"


# ---------------------------------------------------------------------------
# On the explore answer
# ---------------------------------------------------------------------------
async def test_explore_says_roughly_where_the_phone_is(
    auth_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, _feature("Karatina Town", KARATINA, level="town"))

    response = await auth_client.post("/v1/me/explore", json=KARATINA.as_payload())

    assert response.status_code == 200
    assert response.json()["near"] == {
        "name": "Karatina Town",
        "level": "town",
        "ward": "Ruring'u",
    }


async def test_at_home_the_place_is_named_too(
    auth_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The label is about where the phone is, home or not."""
    await _seed(db_session, _feature("Gatitu", NYERI_TOWN))

    response = await auth_client.post("/v1/me/explore", json=NYERI_TOWN.as_payload())

    body = response.json()
    assert body["same_area_as_home"] is True
    assert body["near"]["name"] == "Gatitu"


async def test_where_nothing_is_seeded_near_is_null(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post("/v1/me/explore", json=KARATINA.as_payload())

    assert response.status_code == 200
    assert response.json()["near"] is None


async def test_naming_a_place_writes_nothing(
    auth_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Places are reference data: asking where you are leaves no row behind."""
    await _seed(db_session, _feature("Karatina Town", KARATINA, level="town"))
    before = (await db_session.execute(select(func.count()).select_from(Place))).scalar_one()

    await auth_client.post("/v1/me/explore", json=KARATINA.as_payload())

    after = (await db_session.execute(select(func.count()).select_from(Place))).scalar_one()
    assert after == before


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
async def test_seeding_replaces_a_countys_places(db_session: AsyncSession) -> None:
    await _seed(
        db_session,
        _feature("Old name", NYERI_TOWN),
        _feature("Elsewhere", KARATINA, county="Kirinyaga"),
    )

    await _seed(db_session, _feature("Gatitu", NYERI_TOWN, multi=True))

    names = set((await db_session.execute(select(Place.name, Place.county))).all())
    assert names == {("Gatitu", "Nyeri"), ("Elsewhere", "Kirinyaga")}


def test_excluded_sources_are_left_out() -> None:
    data = _collection(
        _feature("Gatitu", NYERI_TOWN, source="osm"),
        _feature("Polling place", KARATINA, source="iebc-polling-2012"),
        _feature("Both", KARATINA, source="geonames;iebc-polling-2012"),
    )

    places = parse_places(data, exclude_sources=frozenset({"iebc-polling-2012"}))

    assert [place.name for place in places] == ["Gatitu"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"level": "estate"}, "unknown level"),
        ({"name": "  "}, "no name"),
        ({"county": None}, "no county"),
        ({"name": "x" * 121}, "longer than"),
    ],
)
def test_a_bad_place_stops_the_whole_seed(change: dict[str, Any], message: str) -> None:
    """Refused rather than skipped: a silently dropped place is a hole in the map."""
    feature = _feature("Gatitu", NYERI_TOWN)
    feature["properties"].update(change)

    with pytest.raises(SeedError, match=message):
        parse_places(_collection(feature), exclude_sources=frozenset())


def test_a_point_is_not_a_place() -> None:
    feature = _feature("Gatitu", NYERI_TOWN)
    feature["geometry"] = {"type": "Point", "coordinates": [36.95, -0.42]}

    with pytest.raises(SeedError, match="not a polygon"):
        parse_places(_collection(feature), exclude_sources=frozenset())


def test_seed_places_keep_their_details() -> None:
    data = _collection(_feature("Gatitu", NYERI_TOWN))

    (place,) = parse_places(data, exclude_sources=frozenset())

    assert isinstance(place, SeedPlace)
    assert (place.ward, place.sub_county, place.county, place.confidence) == (
        "Ruring'u",
        "Nyeri Central",
        "Nyeri",
        "generated cell",
    )

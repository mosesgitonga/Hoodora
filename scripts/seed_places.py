"""Load named places from GeoJSON, for telling someone roughly where they are.

    uv run python -m scripts.seed_places seeds/places/nyeri.geojson
    uv run python -m scripts.seed_places seeds/places/nyeri.geojson --dry-run
    uv run python -m scripts.seed_places nyeri.geojson --exclude-source iebc-polling-2012

Places are what Home names as "near Gatitu" (decision L.4), shown only to the
person standing there. They are not `areas`, which name places to other people
under k-anonymity; see `scripts/seed_areas.py` for those.

The file is a FeatureCollection of Polygon or MultiPolygon features with at least
`name`, `level` and `county`, and optionally `ward`, `sub_county`, `source` and
`confidence`: the format of the findme pipeline's `nyeri_places.geojson`. A
county's places should not overlap.

Each run **replaces** the places of every county in the file, in one
transaction, so a rebuilt dataset swaps in whole. Feature ids are not used: the
findme build regenerates them.

`--exclude-source` leaves out features whose `source` lists that source (it can
be given more than once), for data whose redistribution terms are unconfirmed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import sys
from dataclasses import dataclass
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import cast as sa_cast
from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import dispose_engine, execute_dml, session_scope
from app.core.logging import configure_logging, safe_extra
from app.modules.location.models import Place

logger = logging.getLogger("scripts.seed_places")

LEVELS = frozenset({"town", "village", "sublocation", "ward"})


class SeedError(Exception):
    """A file that cannot be trusted. Raised rather than skipped: a silently
    dropped place is a hole where nobody is told where they are."""


@dataclass(frozen=True, slots=True)
class SeedPlace:
    name: str
    level: str
    ward: str | None
    sub_county: str | None
    county: str
    source: str
    confidence: str
    geometry: dict[str, Any]


def _text(properties: dict[str, Any], key: str, *, limit: int, required: bool) -> str | None:
    value = properties.get(key)
    text = str(value).strip() if value is not None else ""
    if not text:
        if required:
            raise SeedError(f"a place has no {key}")
        return None
    if len(text) > limit:
        raise SeedError(f"{key} longer than {limit} characters: {text[:40]}…")
    return text


def parse_places(data: dict[str, Any], *, exclude_sources: frozenset[str]) -> list[SeedPlace]:
    if data.get("type") != "FeatureCollection":
        raise SeedError("not a GeoJSON FeatureCollection")
    places: list[SeedPlace] = []
    for feature in data.get("features") or []:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise SeedError(f"{properties.get('name')!r} is not a polygon")
        source = _text(properties, "source", limit=300, required=False) or "unknown"
        if exclude_sources & {part.strip() for part in source.split(";")}:
            continue
        level = _text(properties, "level", limit=20, required=True) or ""
        if level not in LEVELS:
            raise SeedError(f"unknown level {level!r}")
        places.append(
            SeedPlace(
                name=_text(properties, "name", limit=120, required=True) or "",
                level=level,
                ward=_text(properties, "ward", limit=120, required=False),
                sub_county=_text(properties, "sub_county", limit=120, required=False),
                county=_text(properties, "county", limit=120, required=True) or "",
                source=source,
                confidence=_text(properties, "confidence", limit=40, required=False) or "unknown",
                geometry=geometry,
            )
        )
    return places


def _multipolygon(geometry: dict[str, Any]) -> str:
    """The column is MultiPolygon for every place, so queries never branch."""
    if geometry["type"] == "Polygon":
        geometry = {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}
    return json.dumps(geometry)


async def load_places(session: AsyncSession, places: list[SeedPlace]) -> dict[str, int]:
    """Replace the places of every county in `places`. Call inside a transaction."""
    counties = sorted({place.county for place in places})
    removed = 0
    for county in counties:
        removed += await execute_dml(session, delete(Place).where(Place.county == county))
    for place in places:
        session.add(
            Place(
                name=place.name,
                level=place.level,
                ward=place.ward,
                sub_county=place.sub_county,
                county=place.county,
                source=place.source,
                confidence=place.confidence,
                # PostGIS reads the GeoJSON and validates the rings; the cast gives
                # the geography the column wants.
                boundary=sa_cast(
                    func.ST_Multi(func.ST_GeomFromGeoJSON(_multipolygon(place.geometry))),
                    Geography(geometry_type="MULTIPOLYGON", srid=4326),
                ),
            )
        )
    await session.flush()
    return {"counties": len(counties), "removed": removed, "loaded": len(places)}


def read_places(path: pathlib.Path, *, exclude_sources: frozenset[str]) -> list[SeedPlace]:
    """Read and check the whole file before anything touches the database."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedError(f"not JSON: {exc}") from exc
    return parse_places(data, exclude_sources=exclude_sources)


async def main_async(path: pathlib.Path, *, exclude_sources: frozenset[str], dry_run: bool) -> int:
    settings = get_settings()
    configure_logging(settings, service="seed_places")
    try:
        places = read_places(path, exclude_sources=exclude_sources)
    except FileNotFoundError:
        logger.error("seed_file_missing", extra={"path": str(path)})
        return 2
    except SeedError as exc:
        logger.error("seed_invalid", extra={"error": str(exc)})
        return 1
    if dry_run:
        logger.info("places_would_load", extra={"places": len(places)})
        return 0
    try:
        async with session_scope() as session:
            counts = await load_places(session, places)
    finally:
        await dispose_engine()
    logger.info("places_loaded", extra=safe_extra({"path": path.name, **counts}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=pathlib.Path, help="GeoJSON file")
    parser.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        help="Leave out features whose source lists this one. Repeatable.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Check and count only.")
    args = parser.parse_args()
    return asyncio.run(
        main_async(args.path, exclude_sources=frozenset(args.exclude_source), dry_run=args.dry_run)
    )


if __name__ == "__main__":
    sys.exit(main())

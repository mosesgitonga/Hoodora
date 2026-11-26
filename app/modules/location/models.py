"""Location models: seeded areas, and the density table the radius engine reads.

Note what is *not* here: there is no table of user locations. A user's home cell
lives on the user row and is overwritten on change, and explore-mode locations
never leave Redis. Keeping no location history is a deliberate data-protection
choice, not an oversight — see decision 1.1 and `docs/DATA_MAP.md`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    pass


class AreaKind:
    """The kinds of area that can be seeded.

    A plain string column with these as the known values, rather than a database
    enum: the brief requires new towns to work from configuration and seed data
    alone, and a database enum would mean a migration before Nanyuki could use a
    kind Nyeri never needed.
    """

    ESTATE = "estate"
    WARD = "ward"
    TOWN = "town"
    SUBURB = "suburb"
    COUNTY = "county"
    LANDMARK = "landmark"
    CAMPUS = "campus"

    ALL = (ESTATE, WARD, TOWN, SUBURB, COUNTY, LANDMARK, CAMPUS)


class Area(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An administrator-defined named place, used to label approximate locations.

    These are the human-readable half of the privacy model. A user's position is
    never shown; instead the coarse H3 cell that satisfies k-anonymity is resolved
    to the name of the area containing it — "Kamakwa", "Ruring'u" — or falls back
    to something generic like "near Nyeri town".

    Seeded, never user-created: `scripts/seed_areas.py` loads GeoJSON from
    `seeds/areas/`. Nothing about Nyeri is hardcoded in the application; adding a
    town is a seed file.
    """

    __tablename__ = "areas"

    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32), index=True)

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("areas.id", ondelete="SET NULL"), nullable=True
    )
    """Areas nest: an estate inside a ward inside a town. The label falls back up
    this chain when the finest area is too small to name safely."""

    town: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    county: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    boundary: Mapped[object] = mapped_column(
        Geography(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True)
    )
    """Always a MultiPolygon, even for a single-ring estate. One type means
    queries never have to branch, and real administrative boundaries are
    frequently discontiguous anyway."""

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    """Retiring an area keeps old references resolvable while removing it from new
    labelling, which a delete would not."""

    parent: Mapped[Area | None] = relationship(remote_side="Area.id", lazy="raise")

    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="area_parent_not_self"),
        Index(
            "ix_areas_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<Area {self.name} ({self.kind})>"


class CellActivity(Base):
    """Per-cell population counts, refreshed by a worker every fifteen minutes.

    This is what makes the radius adaptive. Counting active users live, per
    request, would mean a aggregate query over the whole users table on every feed
    load; instead the worker precomputes it and the engine reads a handful of rows.

    Keyed by `(resolution, cell)` rather than one table per resolution, because
    two different features need different resolutions: the radius engine walks
    res-8 rings, while k-anonymity needs registered counts at res 8, 7, and 6 to
    decide how coarse an area label has to be.
    """

    __tablename__ = "cell_activity"

    resolution: Mapped[int] = mapped_column(Integer, primary_key=True)

    cell: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    """H3 index as a 64-bit integer. Stored as BIGINT rather than its hex string:
    it is half the size, compares faster, and is what H3 natively is."""

    active_user_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    """Users whose home is in this cell and who opened the app inside the active
    window. Explore-mode visitors are excluded by design — see decision 1.1."""

    registered_user_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    """Everyone whose home is in this cell, active or not. Used for k-anonymity,
    where what matters is how many people a label could refer to."""

    recent_post_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    """Feed posts placed in this cell within `FEED_RECENT_POST_DAYS`, at most
    `FEED_MAX_POSTS_PER_AUTHOR` per author across the whole window: the radius
    engine's second condition (decision T.2). A count, nothing about who."""

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    """Staleness is visible, so the engine can tell "nobody is here" from
    "the refresh has not run". Phase 8 alerts on it."""

    __table_args__ = (
        CheckConstraint("active_user_count >= 0", name="cell_activity_active_non_negative"),
        CheckConstraint("recent_post_count >= 0", name="cell_activity_recent_posts_non_negative"),
        CheckConstraint(
            "registered_user_count >= active_user_count",
            name="cell_activity_active_within_registered",
        ),
        # The engine reads many cells at one resolution at a time.
        Index("ix_cell_activity_resolution_active", "resolution", "active_user_count"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<CellActivity r{self.resolution}/{self.cell} active={self.active_user_count}>"


class UserZoneDay(Base):
    """On which of the last seven days someone was in a zone (decision L.2).

    A zone is an H3 resolution-7 cell, about 2.5 km across. One row per person
    per zone they were in this week, holding seven bits, one per day: bit 0 is
    `updated_on`, higher bits are earlier days. Recorded whenever the app reports
    where the phone is. No coordinates, no times of day, and nothing older than a
    week: a row whose days have all aged out is deleted by the nightly roll.

    Posting in a zone needs `POSTING_PRESENCE_DAYS` of the last seven there or in
    a touching zone.
    """

    __tablename__ = "user_zone_days"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    zone: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    days_mask: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_on: Mapped[date] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("days_mask >= 0 AND days_mask < 128", name="user_zone_days_mask_is_7_bits"),
        Index("ix_user_zone_days_updated_on", "updated_on"),
    )


class Place(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A named place someone can be told they are in: "near Gatitu".

    Not an `Area`. Areas name a place to *other people*, under k-anonymity, so
    they stay coarse. A place is only ever named to the person standing in it,
    from the cell their phone reported, so it can be a village (decision L.4).

    Loaded from seed data by `scripts/seed_places.py`; nothing about any town is
    in the code. A county's places do not overlap, so a point is in one at most.
    """

    __tablename__ = "places"

    name: Mapped[str] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(String(20))
    """`town`, `village`, `sublocation` or `ward`: how specific the name is."""
    ward: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sub_county: Mapped[str | None] = mapped_column(String(120), nullable=True)
    county: Mapped[str] = mapped_column(String(120), index=True)
    source: Mapped[str] = mapped_column(String(300))
    """Where the name came from, as the dataset records it, for attribution."""
    confidence: Mapped[str] = mapped_column(String(40))
    """`official polygon`, `generated cell` (nearest known place) or `fallback`."""
    boundary: Mapped[object] = mapped_column(
        Geography(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True)
    )


class PresenceCount(Base):
    """How many app users were in a hexagon during an hour (decision D.9).

    Counts only: no account, and nothing that ties one hour to the next for
    anyone. Written hourly by `count_presence`, kept for `PRESENCE_RETENTION_DAYS`.
    """

    __tablename__ = "presence_counts"

    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    resolution: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    cell: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    people: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("people > 0", name="presence_people_positive"),
        CheckConstraint("resolution IN (6, 7, 8)", name="presence_resolution_known"),
        Index("ix_presence_counts_resolution_hour_start", "resolution", "hour_start"),
    )

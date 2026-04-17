from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class UserLocation(Base):
    """A named place the user frequents (home, gym, Tahoe cabin, etc.).

    Used to attach elevation/coordinate context to activities that lack
    ``start_lat``/``start_lng`` (indoor/no-GPS sessions). At most one row
    may have ``is_default=True`` — that row auto-applies to any activity
    with neither coordinates nor an explicit ``location_id``.
    """

    __tablename__ = "user_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

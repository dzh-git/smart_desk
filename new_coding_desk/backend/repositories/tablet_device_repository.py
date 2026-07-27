"""Persistence helpers for trusted tablet bindings."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models.tablet_device import TabletDevice


class TabletDeviceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, device_id: str) -> TabletDevice | None:
        return self.db.get(TabletDevice, device_id)

    def get_by_seat(self, seat_id: int) -> TabletDevice | None:
        return (
            self.db.query(TabletDevice)
            .filter(TabletDevice.seat_id == seat_id)
            .first()
        )

    def list_all(self) -> list[TabletDevice]:
        return (
            self.db.query(TabletDevice)
            .order_by(TabletDevice.seat_id)
            .all()
        )

    def save(self, device: TabletDevice) -> TabletDevice:
        self.db.add(device)
        self.db.commit()
        self.db.refresh(device)
        return device

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import ProjectDataSnapshot, ProjectSpatialUnit, SpatialProject


def _project_payload(row: SpatialProject) -> dict[str, Any]:
    return {
        "project_id": row.id,
        "name": row.name,
        "scope": row.scope if isinstance(row.scope, dict) else {},
        "brief": row.brief if isinstance(row.brief, dict) else {},
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _snapshot_payload(row: ProjectDataSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": row.id,
        "project_id": row.project_id,
        "status": row.status,
        "source_history_ids": row.source_history_ids if isinstance(row.source_history_ids, list) else [],
        "scope": row.scope if isinstance(row.scope, dict) else {},
        "dataset_manifest": row.dataset_manifest if isinstance(row.dataset_manifest, list) else [],
        "datasets": row.datasets if isinstance(row.datasets, dict) else {},
        "quality_report": row.quality_report if isinstance(row.quality_report, dict) else {},
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _unit_payload(row: ProjectSpatialUnit) -> dict[str, Any]:
    return {
        "unit_id": row.unit_id,
        "snapshot_id": row.snapshot_id,
        "name": row.name,
        "unit_type": row.unit_type,
        "geometry": row.geometry if isinstance(row.geometry, dict) else {},
        "parent_id": row.parent_id,
        "status": row.status,
        "properties": row.properties if isinstance(row.properties, dict) else {},
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


class SpatialProjectRepo:
    def create_project(self, *, project_id: str, name: str, scope: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
        session: Session = SessionLocal()
        try:
            row = SpatialProject(id=project_id, name=name, scope=scope, brief=brief)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _project_payload(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_projects(self) -> list[dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            return [_project_payload(row) for row in session.query(SpatialProject).order_by(SpatialProject.updated_at.desc()).all()]
        finally:
            session.close()

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        session: Session = SessionLocal()
        try:
            row = session.get(SpatialProject, project_id)
            return _project_payload(row) if row else None
        finally:
            session.close()

    def create_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        session: Session = SessionLocal()
        try:
            row = ProjectDataSnapshot(**payload)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _snapshot_payload(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any] | None:
        session: Session = SessionLocal()
        try:
            row = session.get(ProjectDataSnapshot, snapshot_id)
            return _snapshot_payload(row) if row and row.project_id == project_id else None
        finally:
            session.close()

    def list_snapshots(self, project_id: str) -> list[dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            rows = session.query(ProjectDataSnapshot).filter_by(project_id=project_id).order_by(ProjectDataSnapshot.created_at.desc()).all()
            return [_snapshot_payload(row) for row in rows]
        finally:
            session.close()

    def add_units(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            records = [ProjectSpatialUnit(**row) for row in rows]
            session.add_all(records)
            session.commit()
            return [_unit_payload(row) for row in records]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_units(self, snapshot_id: str, *, status: str = "", limit: int = 50, offset: int = 0) -> tuple[int, list[dict[str, Any]]]:
        session: Session = SessionLocal()
        try:
            query = session.query(ProjectSpatialUnit).filter_by(snapshot_id=snapshot_id)
            if status:
                query = query.filter_by(status=status)
            total = query.count()
            rows = query.order_by(ProjectSpatialUnit.id.asc()).offset(offset).limit(limit).all()
            return total, [_unit_payload(row) for row in rows]
        finally:
            session.close()

    def get_unit(self, snapshot_id: str, unit_id: str) -> dict[str, Any] | None:
        session: Session = SessionLocal()
        try:
            row = (
                session.query(ProjectSpatialUnit)
                .filter_by(snapshot_id=snapshot_id, unit_id=unit_id)
                .first()
            )
            return _unit_payload(row) if row else None
        finally:
            session.close()

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from modules.history.service import (
    build_detail_payload,
    build_history_list_dedupe_key,
    build_lightweight_list_params,
    serialize_created_at,
)
from core.years import normalize_year, resolve_business_year
from .database import SessionLocal
from .history_keys import build_history_record_id
from .models import AgentSession, AnalysisHistory, PoiResult


def _normalize_history_material(value: Any) -> Any:
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
    except TypeError:
        return value


def _history_material_equal(left: Any, right: Any) -> bool:
    return _normalize_history_material(left) == _normalize_history_material(right)


class HistoryRepo:
    @staticmethod
    def _normalize_source(source: Any, fallback: str = "local") -> str:
        raw = str(source or "").strip().lower()
        if raw in {"gaode", "amap"}:
            return "gaode"
        if raw in {"local", "history", "historical"}:
            return "local"
        return fallback

    @staticmethod
    def _normalize_year(value: Any) -> Optional[int]:
        return normalize_year(value)

    @classmethod
    def _normalize_year_list(cls, params: Dict[str, Any]) -> List[int]:
        years = set()
        for item in (params or {}).get("years") or []:
            normalized = cls._normalize_year(item)
            if normalized is not None:
                years.add(normalized)
        normalized = cls._normalize_year((params or {}).get("year"))
        if normalized is not None:
            years.add(normalized)
        return sorted(years)

    @classmethod
    def _build_snapshot_rows(
        cls,
        params: Dict[str, Any],
        pois: List[Dict[str, Any]],
        poi_results_by_year: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if poi_results_by_year:
            result = []
            for item in poi_results_by_year:
                if not isinstance(item, dict):
                    continue
                result.append(
                    {
                        "source": cls._normalize_source(item.get("source"), cls._normalize_source(params.get("source"))),
                        "year": cls._normalize_year(item.get("year")),
                        "pois": list(item.get("pois") or []),
                    }
                )
            return result

        return [
            {
                "source": cls._normalize_source(params.get("source")),
                "year": cls._normalize_year(params.get("year")),
                "pois": list(pois or []),
            }
        ]

    @classmethod
    def _merge_history_params(
        cls,
        current_params: Dict[str, Any],
        next_params: Dict[str, Any],
        snapshot_rows: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        merged = dict(current_params or {})
        merged.update(next_params or {})

        years = set(cls._normalize_year_list(current_params or {}))
        years.update(cls._normalize_year_list(next_params or {}))
        for snapshot in snapshot_rows:
            normalized = cls._normalize_year(snapshot.get("year"))
            if normalized is not None:
                years.add(normalized)

        merged["years"] = sorted(years)
        selected_year = cls._normalize_year((next_params or {}).get("year"))
        if selected_year is None and merged["years"]:
            selected_year = merged["years"][-1]
        merged["year"] = selected_year
        merged["source"] = cls._normalize_source((next_params or {}).get("source"), cls._normalize_source((current_params or {}).get("source")))
        return merged

    @classmethod
    def _build_snapshot_material(cls, snapshot_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = {}
        for snapshot in snapshot_rows:
            key = (cls._normalize_source(snapshot.get("source")), cls._normalize_year(snapshot.get("year")))
            pois = list(snapshot.get("pois") or [])
            result[key] = {
                "pois": pois,
                "summary": {
                    "total": len(pois),
                    "source": key[0],
                    "year": key[1],
                },
            }
        return result

    @staticmethod
    def _build_history_agent_count_map(session: Session, history_ids: Optional[List[str]] = None) -> Dict[str, int]:
        query = session.query(AgentSession.history_id, func.count(AgentSession.id))
        if history_ids is not None:
            if not history_ids:
                return {}
            query = query.filter(AgentSession.history_id.in_(history_ids))
        rows = query.group_by(AgentSession.history_id).all()
        counter: Dict[str, int] = {}
        for history_id_value, count in rows:
            history_id = str(history_id_value or "").strip()
            if not history_id:
                continue
            counter[history_id] = int(count or 0)
        return counter

    @classmethod
    def _collect_available_years(cls, history: AnalysisHistory, poi_rows: List[PoiResult]) -> List[int]:
        years = set(cls._normalize_year_list(history.params if isinstance(history.params, dict) else {}))
        for row in poi_rows:
            normalized = cls._normalize_year(row.year)
            if normalized is not None:
                years.add(normalized)
        return sorted(years)

    @classmethod
    def _resolve_selected_year(
        cls,
        history: AnalysisHistory,
        poi_rows: List[PoiResult],
        requested_year: Optional[int],
    ) -> Optional[int]:
        available_years = cls._collect_available_years(history, poi_rows)
        fallback = (history.params or {}).get("year") if isinstance(history.params, dict) else None
        return resolve_business_year(available_years or [fallback], requested_year)

    @classmethod
    def _select_snapshot_row(
        cls,
        poi_rows: List[Any],
        selected_year: Optional[int],
    ) -> Optional[Any]:
        if selected_year is not None:
            for row in reversed(poi_rows):
                if cls._normalize_year(row.year) == selected_year:
                    return row
        if poi_rows:
            return poi_rows[-1]
        return None

    @staticmethod
    def _build_pois_by_year_payload(poi_rows: List[Any]) -> List[Dict[str, Any]]:
        result = []
        for row in poi_rows:
            summary = row.summary if isinstance(row.summary, dict) else {}
            result.append(
                {
                    "year": HistoryRepo._normalize_year(row.year),
                    "source": HistoryRepo._normalize_source(row.source),
                    "count": int(summary.get("total") or 0),
                    "summary": summary,
                }
            )
        return result

    @staticmethod
    def _get_lightweight_poi_rows(session: Session, history_id: str) -> List[Any]:
        return (
            session.query(
                PoiResult.id,
                PoiResult.source,
                PoiResult.year,
                PoiResult.summary,
                PoiResult.created_at,
            )
            .filter_by(history_id=history_id)
            .order_by(PoiResult.created_at.asc(), PoiResult.id.asc())
            .all()
        )

    @staticmethod
    def _get_poi_data_by_id(session: Session, poi_result_id: Any) -> List[Dict[str, Any]]:
        if poi_result_id is None:
            return []
        row = session.query(PoiResult.poi_data).filter(PoiResult.id == poi_result_id).first()
        poi_data = row[0] if row else []
        return poi_data if isinstance(poi_data, list) else []

    def create_record(
        self,
        params: Dict,
        polygon: List,
        pois: List[Dict],
        description: str = "",
        *,
        preferred_history_id: str = "",
        poi_results_by_year: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        session: Session = SessionLocal()
        try:
            history_id = str(preferred_history_id or "").strip()
            history = session.get(AnalysisHistory, history_id) if history_id else None
            if history is None:
                history_id = build_history_record_id(params, polygon)
                history = session.get(AnalysisHistory, history_id)

            snapshot_rows = self._build_snapshot_rows(params, pois, poi_results_by_year)
            next_params = self._merge_history_params(history.params if history is not None and isinstance(history.params, dict) else {}, params, snapshot_rows)
            next_snapshot_material = self._build_snapshot_material(snapshot_rows)
            existing_rows = self._get_lightweight_poi_rows(session, history_id) if history_id else []

            if history is None:
                history = AnalysisHistory(
                    id=history_id,
                    params=next_params,
                    result_polygon=polygon,
                    description=description,
                    created_at=datetime.utcnow(),
                )
                session.add(history)
            else:
                current_snapshot_material = {}
                for row in existing_rows:
                    key = (self._normalize_source(row.source), self._normalize_year(row.year))
                    if key not in next_snapshot_material:
                        continue
                    row_pois = self._get_poi_data_by_id(session, row.id)
                    current_snapshot_material[key] = {
                        "pois": row_pois,
                        "summary": row.summary if isinstance(row.summary, dict) else {},
                    }
                material_changed = not (
                    _history_material_equal(history.params, next_params)
                    and _history_material_equal(history.result_polygon, polygon)
                    and str(history.description or "") == str(description or "")
                    and _history_material_equal(current_snapshot_material, next_snapshot_material)
                )
                if not material_changed:
                    session.commit()
                    return history_id
                history.params = next_params
                history.result_polygon = polygon
                history.description = description
                history.created_at = datetime.utcnow()

            existing_ids_by_key = {
                (self._normalize_source(row.source), self._normalize_year(row.year)): row.id
                for row in existing_rows
            }
            for snapshot in snapshot_rows:
                source = self._normalize_source(snapshot.get("source"))
                year = self._normalize_year(snapshot.get("year"))
                row_pois = list(snapshot.get("pois") or [])
                summary = {
                    "total": len(row_pois),
                    "source": source,
                    "year": year,
                }
                poi_record_id = existing_ids_by_key.get((source, year))
                if row_pois:
                    if poi_record_id is None:
                        session.add(
                            PoiResult(
                                history_id=history_id,
                                source=source,
                                year=year,
                                poi_data=row_pois,
                                summary=summary,
                            )
                        )
                    else:
                        poi_record = session.get(PoiResult, poi_record_id)
                        if poi_record is None:
                            continue
                        poi_record.source = source
                        poi_record.year = year
                        poi_record.poi_data = row_pois
                        poi_record.summary = summary
                        poi_record.created_at = datetime.utcnow()
                elif poi_record_id is not None:
                    poi_record = session.get(PoiResult, poi_record_id)
                    if poi_record is None:
                        continue
                    session.delete(poi_record)

            session.commit()
            return history_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_list(self, limit: int = 0) -> List[Dict]:
        session: Session = SessionLocal()
        try:
            query = (
                session.query(
                    AnalysisHistory.id,
                    AnalysisHistory.description,
                    AnalysisHistory.created_at,
                )
                .order_by(desc(AnalysisHistory.created_at))
            )
            if isinstance(limit, int) and limit > 0:
                query = query.limit(limit)
            records = query.all()
            history_ids = [str(row.id) for row in records]
            ai_count_map = self._build_history_agent_count_map(session, history_ids)
            lightweight_rows = (
                session.query(
                    AnalysisHistory.id,
                    func.json_extract(AnalysisHistory.params, "$.center").label("center"),
                    func.json_extract(AnalysisHistory.params, "$.time_min").label("time_min"),
                    func.json_extract(AnalysisHistory.params, "$.keywords").label("keywords"),
                    func.json_extract(AnalysisHistory.params, "$.mode").label("mode"),
                    func.json_extract(AnalysisHistory.params, "$.source").label("source"),
                    func.json_extract(AnalysisHistory.params, "$.year").label("year"),
                    func.json_extract(AnalysisHistory.params, "$.years").label("years"),
                )
                .filter(AnalysisHistory.id.in_(history_ids))
                .all()
                if history_ids
                else []
            )
            lightweight_by_id = {str(row.id): row for row in lightweight_rows}

            result = []
            seen_keys = set()
            for row in records:
                list_params = build_lightweight_list_params(lightweight_by_id.get(str(row.id)))
                dedupe_key = build_history_list_dedupe_key(row.description, list_params)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                result.append(
                    {
                        "id": row.id,
                        "description": row.description,
                        "created_at": serialize_created_at(row.created_at),
                        "params": list_params,
                        "ai_session_count": int(ai_count_map.get(str(row.id), 0)),
                    }
                )
            return result
        finally:
            session.close()

    def get_detail(self, history_id: str, include_pois: bool = True, year: Optional[int] = None) -> Optional[Dict]:
        session: Session = SessionLocal()
        try:
            history = session.query(AnalysisHistory).filter_by(id=history_id).first()
            if not history:
                return None
            if not include_pois:
                poi_rows = (
                    session.query(
                        PoiResult.source,
                        PoiResult.year,
                        PoiResult.summary,
                    )
                    .filter_by(history_id=history_id)
                    .order_by(PoiResult.created_at.asc(), PoiResult.id.asc())
                    .all()
                )
                available_years = set(self._normalize_year_list(history.params if isinstance(history.params, dict) else {}))
                for row in poi_rows:
                    normalized = self._normalize_year(row.year)
                    if normalized is not None:
                        available_years.add(normalized)
                sorted_years = sorted(available_years)
                fallback = (history.params or {}).get("year") if isinstance(history.params, dict) else None
                selected_year = resolve_business_year(sorted_years or [fallback], year)

                selected_summary: Dict[str, Any] = {}
                for row in reversed(poi_rows):
                    if selected_year is None or self._normalize_year(row.year) == selected_year:
                        selected_summary = row.summary if isinstance(row.summary, dict) else {}
                        break
                poi_count = int(selected_summary.get("total") or 0) if isinstance(selected_summary, dict) else 0
                pois_by_year = [
                    {
                        "year": self._normalize_year(row.year),
                        "source": self._normalize_source(row.source),
                        "count": int((row.summary or {}).get("total") or 0) if isinstance(row.summary, dict) else 0,
                        "summary": row.summary if isinstance(row.summary, dict) else {},
                    }
                    for row in poi_rows
                ]
                return build_detail_payload(
                    history,
                    pois=None,
                    poi_summary=selected_summary,
                    poi_count=poi_count,
                    available_years=sorted_years,
                    selected_year=selected_year,
                    pois_by_year=pois_by_year,
                )

            poi_rows = self._get_lightweight_poi_rows(session, history_id)
            available_years = self._collect_available_years(history, poi_rows)
            selected_year = self._resolve_selected_year(history, poi_rows, year)
            selected_row = self._select_snapshot_row(poi_rows, selected_year)
            pois = self._get_poi_data_by_id(session, selected_row.id if selected_row else None)
            poi_summary = selected_row.summary if selected_row and isinstance(selected_row.summary, dict) else {}
            pois_by_year = self._build_pois_by_year_payload(poi_rows)
            return build_detail_payload(
                history,
                pois=pois if include_pois else None,
                poi_summary=poi_summary,
                poi_count=len(pois),
                available_years=available_years,
                selected_year=selected_year,
                pois_by_year=pois_by_year,
            )
        finally:
            session.close()

    def get_pois(self, history_id: str, year: Optional[int] = None) -> Optional[Dict]:
        session: Session = SessionLocal()
        try:
            history = session.query(AnalysisHistory).filter_by(id=history_id).first()
            if not history:
                return None
            poi_rows = self._get_lightweight_poi_rows(session, history_id)
            available_years = self._collect_available_years(history, poi_rows)
            selected_year = self._resolve_selected_year(history, poi_rows, year)
            selected_row = self._select_snapshot_row(poi_rows, selected_year)
            pois = self._get_poi_data_by_id(session, selected_row.id if selected_row else None)
            poi_summary = selected_row.summary if selected_row and isinstance(selected_row.summary, dict) else {}
            return {
                "history_id": history_id,
                "polygon": history.result_polygon,
                "pois": pois,
                "poi_summary": poi_summary,
                "count": len(pois),
                "available_years": available_years,
                "selected_year": selected_year,
            }
        finally:
            session.close()

    def delete_record(self, history_id: str) -> bool:
        session: Session = SessionLocal()
        try:
            target_history_id = str(history_id).strip()
            session.query(AgentSession).filter_by(history_id=target_history_id).delete()
            session.query(PoiResult).filter_by(history_id=history_id).delete()
            rows = session.query(AnalysisHistory).filter_by(id=history_id).delete()
            session.commit()
            return rows > 0
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()


history_repo = HistoryRepo()

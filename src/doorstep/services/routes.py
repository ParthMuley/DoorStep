"""Route constraints + HERE polyline post-check (contract v2.1 §5.10).

The Route agent calls HERE; B decides what to avoid and whether the returned line
is acceptable. ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION. Never "safe".
* avoid: active simulated ORDER polygons + OFFICIAL_CONFIRMED closures (buffered)
* cautions: UNVERIFIED_REPORT / CONFLICTING closures (never blocks, never "open")
* refuse: a stop inside an ORDER zone, stale/unknown zone data, too many avoid areas,
  transport not accepted; post-check refuses any line crossing an ORDER zone or an
  official closure, or HERE notices that an avoid was violated.
"""

from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, Any, Optional

from shapely.geometry import shape

from doorstep.models import ServiceStatus as S, ServiceType, utc_now_iso
from doorstep.models.closures import RoutePreview, RouteRequest

from . import geo
from .closures import segment_area
from .errors import Conflict, NotFound

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

LABEL = "ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION"
ETA_LABEL = "Estimate only, not a guarantee"
TRANSPORT = ServiceType.ACCESSIBLE_TRANSPORT.value
DESTINATION = ServiceType.ACCESSIBLE_DESTINATION.value


def _strip(doc: Optional[dict]) -> dict:
    return {k: v for k, v in (doc or {}).items() if not k.startswith("_")}


def _crosses(line, area) -> bool:
    return line.intersects(area) and not line.touches(area)


class RouteService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.store = engine.store
        self.events = engine.events

    @staticmethod
    def max_avoid_areas() -> int:
        return int(os.environ.get("ROUTE_MAX_AVOID_AREAS", "20"))  # HERE v8 accepts at most 20 polygons

    # ------------------------------------------------------------ geometry
    def _order_areas(self) -> list[tuple[str, Any]]:
        out = []
        for a in self.engine.alerts._alerts({"active": True, "source_type": "OFFICIAL_SIMULATION", "status": "ORDER"}):
            g = geo.polygon(a.geometry)
            if g is not None:
                out.append((a.alert_id, g))
        return out

    def _official_areas(self) -> list[tuple[str, Any]]:
        return [(c.closure_id, segment_area(c.segment_id)) for c in self.engine.closures.blocking()]

    def _caution_areas(self) -> list[tuple[str, Any, Any]]:
        return [(c.closure_id, segment_area(c.segment_id), c) for c in self.engine.closures.cautions()]

    def _stops(self, transport) -> list[dict[str, Any]]:
        case = self.store.get_case(transport.case_id)
        profile = self.store.get_resident_profile(case.resident_id)
        stops = []
        found = self.store.partners.locate_volunteer(transport.volunteer_id) if transport.volunteer_id else None
        if found:
            v = found[2]
            stops.append({"role": "VOLUNTEER_START", "lat": v.location.lat, "lon": v.location.lon,
                          "label": "Volunteer start (synthetic)"})
        stops.append({"role": "PICKUP", "lat": profile.address.lat, "lon": profile.address.lon,
                      "label": "Synthetic pickup area"})
        shelter = self.store.accepted_assignment(case.case_id, DESTINATION) or self.engine._linked(transport)
        if shelter and shelter.site_id:
            site = self.store.partners.locate_site(shelter.site_id)
            if site:
                stops.append({"role": "SHELTER", "lat": site[2].location.lat, "lon": site[2].location.lon,
                              "label": site[2].name})
        return stops

    # --------------------------------------------------------- constraints
    def constraints(self, assignment_id: str, *, idempotency_key: Optional[str] = None,
                    correlation_id: Optional[str] = None) -> dict[str, Any]:
        eng = self.engine
        transport = self.store.get_assignment(assignment_id)
        if transport.service_type != TRANSPORT:
            transport = eng._linked(transport) or transport
        case = self.store.get_case(transport.case_id)
        corr = eng._corr(case, correlation_id)
        key = idempotency_key or f"{assignment_id}:route:{utc_now_iso()}"
        prior = self.db.coll("route_requests").find_one({"_key": key})
        if prior:
            return {**self._constraints_view(RouteRequest.model_validate(_strip(prior)), corr), "duplicate": True}

        reasons: list[str] = []
        if transport.service_type != TRANSPORT or transport.status != S.ACCEPTED:
            reasons.append("ASSIGNMENT_NOT_ACCEPTED")
        zone = eng.alerts.zone_for(self.store.get_resident_profile(case.resident_id))["zone_status"]
        if zone == "STALE":
            reasons.append("ZONE_STALE")
        elif zone == "UNKNOWN":
            reasons.append("ZONE_UNKNOWN")
        stops = self._stops(transport)
        orders = self._order_areas()
        from shapely.geometry import Point
        if any(area.covers(Point(s["lon"], s["lat"])) for s in stops for _, area in orders):
            reasons.append("ORDER_ZONE")
        avoid = orders + self._official_areas()
        if len(avoid) > self.max_avoid_areas():
            reasons.append("TOO_MANY_AVOID_AREAS")  # refuse rather than silently truncate
        cautions = self._caution_areas()
        req = RouteRequest(route_request_id=self.db.next_id("route"), case_id=case.case_id,
                           assignment_id=transport.assignment_id, status="REFUSED" if reasons else "OK",
                           refusal_reasons=reasons, stops=stops, avoid_area_ids=[i for i, _ in avoid],
                           caution_ids=[i for i, _, _ in cautions], created_at=utc_now_iso())
        self.db.coll("route_requests").update_one({"_id": req.route_request_id},
                                                  {"$set": {**req.model_dump(mode="json"), "_key": key}}, upsert=True)
        self.events.append("ROUTE_CONSTRAINTS_REFUSED" if reasons else "ROUTE_CONSTRAINTS_ISSUED",
                           case_id=case.case_id, correlation_id=corr,
                           data={"route_request_id": req.route_request_id, "reasons": reasons,
                                 "avoid_areas": len(avoid), "cautions": len(cautions)})
        if reasons:
            raise Conflict("Route constraints refused", code="ROUTE_REFUSED", reasons=reasons)
        return {**self._constraints_view(req, corr), "duplicate": False}

    def _constraints_view(self, req: RouteRequest, corr: str) -> dict[str, Any]:
        avoid = [{"kind": "ORDER_ZONE", "id": i, "geometry": a.__geo_interface__} for i, a in self._order_areas()
                 if i in req.avoid_area_ids]
        avoid += [{"kind": "OFFICIAL_CLOSURE", "id": i, "geometry": a.__geo_interface__}
                  for i, a in self._official_areas() if i in req.avoid_area_ids]
        cautions = [{"closure_id": i, "state": c.state, "road_name": c.road_name, "geometry": a.__geo_interface__}
                    for i, a, c in self._caution_areas() if i in req.caution_ids]
        return {"route_request_id": req.route_request_id, "status": req.status, "stops": req.stops,
                "avoid_areas": avoid, "cautions": cautions, "max_avoid_areas": self.max_avoid_areas(),
                "data_as_of": req.created_at, "label": LABEL, "correlation_id": corr}

    # ---------------------------------------------------------- post-check
    def preview(self, route_request_id: str, *, provider: str, polyline: Optional[dict], distance_m: Optional[float],
                duration_s: Optional[float], provider_notices: list[Any], idempotency_key: Optional[str] = None,
                correlation_id: Optional[str] = None) -> dict[str, Any]:
        eng = self.engine
        d = self.db.coll("route_requests").find_one({"_id": route_request_id})
        if not d:
            raise NotFound(f"Route request {route_request_id!r} not found")
        req = RouteRequest.model_validate(_strip(d))
        if req.status != "OK":
            raise Conflict("Route request was refused; no preview can be accepted", code="ROUTE_REFUSED",
                           reasons=req.refusal_reasons)
        case = self.store.get_case(req.case_id)
        corr = eng._corr(case, correlation_id)
        key = idempotency_key or f"{route_request_id}:preview"
        prior = self.db.coll("route_previews").find_one({"_key": key})
        if prior:
            return {**self._preview_view(RoutePreview.model_validate(_strip(prior)), corr), "duplicate": True}

        status, reason, crosses, cautions_hit = "ILLUSTRATIVE_ONLY", None, [], []
        line = None
        if polyline is None:
            status, reason = "NO_ROUTE_CONFIRMED", "PROVIDER_FOUND_NO_ROUTE"
        else:
            try:
                line = shape(polyline)
                if line.geom_type != "LineString" or line.is_empty:
                    raise ValueError
            except Exception:
                raise Conflict("polyline must be a GeoJSON LineString", code="VALIDATION_ERROR")
            zone = eng.alerts.zone_for(self.store.get_resident_profile(case.resident_id))["zone_status"]
            # Re-check against CURRENT data: zones/closures may have changed since the constraints.
            crosses = [i for i, a in self._order_areas() + self._official_areas() if _crosses(line, a)]
            cautions_hit = [i for i, a, _ in self._caution_areas() if _crosses(line, a)]
            violated = any("violat" in str(n).lower() for n in provider_notices or [])
            if zone in ("STALE", "UNKNOWN"):
                status, reason = "REFUSED", f"ZONE_{zone}"
            elif crosses:
                status, reason = "REFUSED", "CROSSES_ORDER_ZONE_OR_OFFICIAL_CLOSURE"
            elif violated:
                status, reason = "REFUSED", "PROVIDER_REPORTED_AVOID_VIOLATION"
        prev = RoutePreview(route_preview_id=self.db.next_id("rprev"), route_request_id=route_request_id,
                            case_id=case.case_id, assignment_id=req.assignment_id, provider=provider, status=status,
                            refusal_reason=reason, crosses=crosses, cautions_on_path=cautions_hit,
                            distance_m=distance_m, duration_s=duration_s, polyline=polyline, created_at=utc_now_iso())
        with self.db.tx():
            self.db.coll("route_previews").update_one({"_id": prev.route_preview_id},
                                                      {"$set": {**prev.model_dump(mode="json"), "_key": key}},
                                                      upsert=True)
            if status == "ILLUSTRATIVE_ONLY" and duration_s:
                transport = self.store.get_assignment(req.assignment_id)
                transport.eta_minutes = max(1, math.ceil(duration_s / 60))
                self.store.save_assignment(transport)
            self.events.append(f"ROUTE_PREVIEW_{status}", case_id=case.case_id, correlation_id=corr,
                               data={"route_preview_id": prev.route_preview_id, "reason": reason,
                                     "crosses": crosses, "cautions": cautions_hit})
        return {**self._preview_view(prev, corr), "duplicate": False}

    def _preview_view(self, p: RoutePreview, corr: str) -> dict[str, Any]:
        return {"route_preview_id": p.route_preview_id, "route_request_id": p.route_request_id, "status": p.status,
                "refusal_reason": p.refusal_reason, "crosses": p.crosses, "cautions_on_path": p.cautions_on_path,
                "distance_m": p.distance_m, "duration_s": p.duration_s,
                "eta": {"minutes": max(1, math.ceil(p.duration_s / 60)), "label": ETA_LABEL}
                if p.status == "ILLUSTRATIVE_ONLY" and p.duration_s else None,
                "label": LABEL, "correlation_id": corr}

    def latest_for_case(self, case_id: str) -> Optional[dict[str, Any]]:
        d = self.db.coll("route_previews").find_one({"case_id": case_id}, sort=[("created_at", -1)])
        return {"route_preview_id": d["route_preview_id"], "status": d["status"],
                "refusal_reason": d.get("refusal_reason")} if d else None

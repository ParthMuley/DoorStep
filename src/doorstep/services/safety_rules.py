"""Fixed-code safety gate. No LLM may override anything in this module.

Rules (master spec Section 0 rules 2-4, Section 5):
* No ordinary volunteer assignment inside or through an active evacuation-order zone.
* Only approved (partner-preapproved) providers can be assigned.
* Routes come from the fictional zone graph, avoid closed edges, and are
  labeled illustrative only -- never "safe".
"""

from __future__ import annotations

from dataclasses import dataclass

from doorstep.demo.synthetic_zone_graph import ZoneGraph
from doorstep.models import Assignment, ZoneRule

ROUTE_DISCLAIMER = "Illustrative route on a fictional graph; not a safety assessment."


@dataclass(frozen=True)
class RouteCheck:
    ok: bool
    path: list[str]
    distance_km: float | None
    reason: str = ""


def zone_rule(graph: ZoneGraph, zone_id: str | None) -> ZoneRule:
    """Unknown location fails closed as UNVERIFIED (blocks ordinary assignment)."""
    if not zone_id or zone_id not in graph.zones:
        return ZoneRule.UNVERIFIED
    return ZoneRule.INSIDE_ACTIVE_ORDER if graph.is_active_order(zone_id) else ZoneRule.OUTSIDE_ACTIVE_ORDER


def check_route(graph: ZoneGraph, start: str, goal: str) -> RouteCheck:
    if graph.is_active_order(start) or graph.is_active_order(goal):
        return RouteCheck(False, [], None, "ROUTE_ENDPOINT_IN_ACTIVE_ORDER_ZONE")
    found = graph.shortest_path(start, goal)
    if found is None:
        return RouteCheck(False, [], None, "NO_PATH_AVOIDING_CLOSED_ROADS_AND_ORDER_ZONES")
    path, km = found
    return RouteCheck(True, path, km)


def assignment_safety_violations(assignment: Assignment) -> list[str]:
    """Reasons an assignment may NOT become active. Empty list == allowed."""
    problems = []
    if not assignment.provider_approved:
        problems.append("PROVIDER_NOT_APPROVED")
    if not assignment.service_area_allowed:
        problems.append("OUTSIDE_PROVIDER_SERVICE_AREA")
    if assignment.zone_rule != ZoneRule.OUTSIDE_ACTIVE_ORDER:
        problems.append("INSIDE_ACTIVE_ORDER_ZONE")
    if assignment.authorization != "SIMULATED_PREAPPROVED":
        problems.append("NOT_AUTHORIZED")
    return problems

"""Synthetic zone graph for the demo. ILLUSTRATIVE ONLY.

These zones and roads are fictional. Nothing here describes a real place, a
real fire perimeter, or a wildfire-safe route. The planner only answers "is
there a path on this fictional graph that avoids active-order zones and
explicitly closed edges?" -- it never claims a route is safe.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Zone:
    zone_id: str
    label: str
    parent_zone: str | None = None  # warnings for a parent cover its children
    active_evacuation_order: bool = False


@dataclass
class ZoneGraph:
    zones: dict[str, Zone]
    # Undirected weighted edges: (a, b) -> synthetic km.
    edges: dict[frozenset[str], float]
    closed_edges: set[frozenset[str]] = field(default_factory=set)

    def is_active_order(self, zone_id: str) -> bool:
        zone = self.zones.get(zone_id)
        return bool(zone and zone.active_evacuation_order)

    def zones_covered_by(self, zone_id: str) -> list[str]:
        """The zone plus any child zones (a warning for zone_3 covers zone_3n)."""
        return [z.zone_id for z in self.zones.values()
                if z.zone_id == zone_id or z.parent_zone == zone_id]

    def neighbors(self, zone_id: str):
        for edge, km in self.edges.items():
            if zone_id in edge and edge not in self.closed_edges:
                (other,) = edge - {zone_id} or {zone_id}
                yield other, km

    def shortest_path(self, start: str, goal: str) -> tuple[list[str], float] | None:
        """Dijkstra on the fictional graph, avoiding closed edges and every
        active-order zone (including as start or goal). None if no path."""
        if start not in self.zones or goal not in self.zones:
            return None
        if self.is_active_order(start) or self.is_active_order(goal):
            return None
        dist = {start: 0.0}
        prev: dict[str, str] = {}
        heap = [(0.0, start)]
        while heap:
            d, node = heapq.heappop(heap)
            if node == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(prev[path[-1]])
                return list(reversed(path)), round(d, 2)
            if d > dist.get(node, float("inf")):
                continue
            for nxt, km in self.neighbors(node):
                if self.is_active_order(nxt):
                    continue
                nd = d + km
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt] = nd
                    prev[nxt] = node
                    heapq.heappush(heap, (nd, nxt))
        return None


def _e(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


def build_demo_graph() -> ZoneGraph:
    """Fresh copy of the fictional demo graph.

    zone_3   -- simulated WARNING area (Maria). Outside any active order.
    zone_3n  -- inside zone_3's warning area, ACTIVE simulated evacuation order (David).
    zone_2   -- transport depot area.        zone_4 -- nearby area.
    zone_5   -- accessible community center area.
    Edge zone_3 <-> zone_4 is CLOSED (simulated road closure).
    """
    zones = {
        "zone_2": Zone("zone_2", "Zone 2 (DEMO depot area)"),
        "zone_3": Zone("zone_3", "Zone 3 (DEMO warning area)"),
        "zone_3n": Zone("zone_3n", "Zone 3 North (DEMO active order)", parent_zone="zone_3",
                        active_evacuation_order=True),
        "zone_4": Zone("zone_4", "Zone 4 (DEMO)"),
        "zone_5": Zone("zone_5", "Zone 5 (DEMO community center area)"),
    }
    edges = {
        _e("zone_2", "zone_3"): 4.0,
        _e("zone_3", "zone_3n"): 1.5,
        _e("zone_3", "zone_4"): 1.0,
        _e("zone_4", "zone_5"): 2.0,
        _e("zone_2", "zone_5"): 5.0,
        _e("zone_3n", "zone_4"): 2.0,
    }
    closed = {_e("zone_3", "zone_4")}
    return ZoneGraph(zones=zones, edges=edges, closed_edges=closed)

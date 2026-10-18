"""Route agent (HERE Routing v8) - DOORSTEP DEMO. Design: team plan rev 4 §0.3.

On `RouteRequest(assignment_id)` (sent by Doorstep after the volunteer accepts):
  1. B `/routes/constraints` -> stops (volunteer start -> pickup -> shelter), avoid areas
     (active ORDER zones + OFFICIAL closures only), cautions (unverified reports) - or a
     refusal (stop inside an order zone, stale/unknown data, too many areas...);
  2. HERE multi-stop route avoiding those areas (refuse instead of truncating);
  3. B `/routes/previews` post-checks the polyline (no order-zone/official-closure crossing,
     data still fresh) and decides ILLUSTRATIVE_ONLY / REFUSED / NO_ROUTE_CONFIRMED.
No LLM anywhere in routing. Never "safe". The ETA is an illustrative estimate.

Free tier: one HERE call per assignment (cached by idempotency key) and a daily cap
(HERE_MAX_CALLS_PER_DAY, default 50); past the cap -> NO_ROUTE_CONFIRMED, no call.

Run:  python -m doorstep.agents.route
"""

import os
from datetime import datetime, timezone
from typing import Any, Callable

from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import build_agent, role_port, seed_for
from doorstep.integrations.fetch_messages import RouteRequest, RouteResponse, utc_now
from doorstep.integrations.here_client import HereRouter, RouteRefused
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()


def daily_cap() -> int:
    return int(os.getenv("HERE_MAX_CALLS_PER_DAY", "50"))


class RouteAgent:
    def __init__(self, get_backend: Callable[[], DoorstepBackendV2], here: HereRouter | None = None):
        self.get_backend = get_backend
        self.here = here or HereRouter()
        self.cache: dict[str, RouteResponse] = {}
        self.calls: dict[str, int] = {}  # UTC day -> HERE calls made (also mirrored to ctx.storage)

    def _reply(self, msg: RouteRequest, status: str, **kw: Any) -> RouteResponse:
        return RouteResponse(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                             assignment_id=msg.assignment_id, status=status, **kw)

    def _budget_ok(self, ctx: Context) -> bool:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        used = self.calls.get(day) or int(ctx.storage.get(f"here_calls:{day}") or 0)
        if used >= daily_cap():
            return False
        self.calls[day] = used + 1
        ctx.storage.set(f"here_calls:{day}", used + 1)
        return True

    async def plan(self, ctx: Context, msg: RouteRequest) -> RouteResponse:
        if msg.idempotency_key in self.cache:  # never pay twice for the same assignment
            return self.cache[msg.idempotency_key]
        backend, corr = self.get_backend(), msg.correlation_id
        try:
            c = await backend.route_constraints(msg.assignment_id, msg.idempotency_key, corr)
        except BackendError as err:
            return self._reply(msg, "REFUSED", reasons=err.reasons or [err.code])
        except OSError:
            return self._reply(msg, "NO_ROUTE_CONFIRMED", reasons=["BACKEND_UNREACHABLE"])

        stops = sorted(c["stops"], key=lambda s: ["VOLUNTEER_START", "PICKUP", "SHELTER"].index(s["role"]))
        avoided = [{"kind": a["kind"], "id": a["id"]} for a in c.get("avoid_areas", [])]
        route, notices, reasons = None, [], []
        try:
            if not self._budget_ok(ctx):
                raise RouteRefused("HERE_DAILY_CAP_REACHED", "daily HERE call cap reached (free tier)")
            route = await self.here.route(stops, c.get("avoid_areas", []))
            if route is None:
                reasons.append("NO_ROUTE_FOUND")
            else:
                notices = route.notices
        except RouteRefused as err:
            reasons.append(err.reason)
            if err.reason in ("TOO_MANY_AVOID_AREAS", "AVOID_AREA_TOO_COMPLEX"):
                return self._remember(msg, self._reply(msg, "REFUSED", reasons=reasons, avoided=avoided))

        try:
            preview = await backend.route_preview(
                c["route_request_id"], route.geojson() if route else None,
                route.distance_m if route else None, route.duration_s if route else None,
                [{"code": n.get("code"), "title": n.get("title"), "severity": n.get("severity")} for n in notices],
                utc_now(), f"{c['route_request_id']}:preview", corr)
        except BackendError as err:
            return self._reply(msg, "REFUSED", reasons=reasons + (err.reasons or [err.code]))
        except OSError:
            return self._reply(msg, "NO_ROUTE_CONFIRMED", reasons=reasons + ["BACKEND_UNREACHABLE"])

        status = preview.get("status", "NO_ROUTE_CONFIRMED")
        if route is not None and route.violated and status == "ILLUSTRATIVE_ONLY":
            status, reasons = "REFUSED", reasons + ["HERE_REPORTED_VIOLATION"]  # both checks must pass
        if status != "ILLUSTRATIVE_ONLY":
            reasons += [f"CROSSES:{x}" for x in preview.get("crosses", [])] + list(preview.get("reasons", []))
            return self._remember(msg, self._reply(msg, status, reasons=reasons, avoided=avoided,
                                                   route_preview_id=preview.get("route_preview_id")))
        eta = (preview.get("eta") or {}).get("minutes")
        return self._remember(msg, self._reply(
            msg, status, route_preview_id=preview.get("route_preview_id"), distance_m=route.distance_m,
            duration_s=route.duration_s, eta_pickup_minutes=round(route.leg_durations_s[0] / 60) if route.leg_durations_s else eta,
            directions=route.directions, avoided=avoided, cautions_on_path=list(preview.get("cautions_on_path", [])),
            label=preview.get("label") or "ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION"))

    def _remember(self, msg: RouteRequest, reply: RouteResponse) -> RouteResponse:
        self.cache[msg.idempotency_key] = reply
        return reply

    def protocol(self) -> Protocol:
        proto = Protocol(name="doorstep_route", version="2.1")

        @proto.on_message(RouteRequest, replies=RouteResponse)
        async def on_route(ctx: Context, sender: str, msg: RouteRequest):
            reply = await self.plan(ctx, msg)
            ctx.logger.info(f"[{msg.correlation_id}] route {msg.assignment_id}: {reply.status} {reply.reasons}")
            await ctx.send(sender, reply)

        return proto


def main() -> None:
    agent = build_agent("doorstep_route", seed_for("ROUTE_SEED"), role_port("ROUTE"), "route.md", "route",
                        "DOORSTEP DEMO: illustrative routes for volunteers (HERE) that avoid simulated evacuation-order "
                        "zones and official closures, checked by the backend. Never a safe-route claim.")
    agent.include(RouteAgent(lambda: DoorstepBackendV2()).protocol(), publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()

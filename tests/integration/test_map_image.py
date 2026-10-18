"""Route map image: HERE Map Image v3 overlays (mocked; no paid calls) and the dev probe."""

from urllib.parse import parse_qsl, urlparse

import flexpolyline
import httpx
import pytest

from doorstep.integrations.map_image import fetch_map_png, image_test_card, route_overlays, tiny_png

STOPS = [{"kind": "VOLUNTEER_START", "lat": 34.099, "lon": -118.095},
         {"kind": "PICKUP", "lat": 34.1012, "lon": -118.0964}, {"kind": "SHELTER", "lat": 34.089, "lon": -118.07}]
ZONE = {"kind": "ORDER_ZONE", "geometry": {"type": "Polygon", "coordinates": [[[-118.1, 34.104], [-118.09, 34.104],
                                                                                [-118.09, 34.11], [-118.1, 34.104]]]}}
ROUTE = [(-118.095, 34.099), (-118.0964, 34.1012), (-118.07, 34.089)]


def test_overlays_draw_zone_route_and_labelled_stops():
    zone, line, points = route_overlays(ROUTE, STOPS, [ZONE])
    assert zone.startswith("polygon:34.10400,-118.10000,") and zone.endswith(";color=#D3242488")  # closed ring, fill only
    assert zone.count(",") == 7  # 4 points incl. the closing one
    encoded = line.removeprefix("line:").split(";")[0]
    assert [tuple(round(v, 4) for v in p) for p in flexpolyline.decode(encoded)] == [(34.099, -118.095),
                                                                                    (34.1012, -118.0964), (34.089, -118.07)]
    assert "label=Pickup" in points and "label=Shelter" in points


async def test_fetch_keeps_the_key_server_side_and_checks_the_response():
    seen = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["query"] = parse_qsl(urlparse(str(request.url)).query)
        return httpx.Response(200, content=tiny_png(), headers={"content-type": "image/png"})

    png = await fetch_map_png(route_overlays(ROUTE, STOPS, [ZONE]), api_key="test-key",
                              transport=httpx.MockTransport(handle))
    assert png.startswith(b"\x89PNG")
    assert ("apiKey", "test-key") in seen["query"] and sum(k == "overlay" for k, _ in seen["query"]) == 3
    assert any("#1565C0" in v for _, v in seen["query"])  # raw "#": httpx encodes it once

    bad = httpx.MockTransport(lambda r: httpx.Response(400, json={"code": "E622002"}))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await fetch_map_png(["point:1,1"], api_key="k", transport=bad)


def test_image_probe_cards():
    assert image_test_card("web").payload["hero_image"].startswith("https://")
    assert "hero_image" not in image_test_card("plain").payload
    assert isinstance(image_test_card("nope"), str)

"""Route map image for the volunteer's trip card. DOORSTEP DEMO.

ASI:One detail cards take `hero_image`: a plain URL string. Tested live (2026-10-18):
  * a public https URL renders, fetched directly by the viewer's browser (no proxy);
  * a data: URI makes ASI:One reject the whole card (text fallback only);
  * http://localhost is blocked by asi1.ai's CSP (img-src 'self' data: blob: https:);
  * cards without buttons (is_terminal) don't render on their own.
So the PNG from HERE Map Image v3 (fetched here, server-side: the key never leaves this
process) must be hosted at a public https URL. Dev probe: `test image <web|data|local|plain>`.
"""

import base64
import os
import struct
import zlib
from typing import Any

import flexpolyline
import httpx

from doorstep.integrations.asi_cards import SIM_PREFIX, Card, _footer, _row

MAP_IMAGE_URL = "https://image.maps.hereapi.com/mia/v3/base/mc/overlay;padding=48/{size}/png8"
ROUTE_STYLE = "color=#1565C0;width=6;outline-color=#FFFFFF;outline-width=2"  # httpx encodes "#"
ORDER_ZONE_STYLE = "color=#D3242488"  # translucent red: evacuation ORDER zone (avoided)
CLOSURE_STYLE = "color=#B71C1CCC"  # official closure buffer (avoided)


def route_overlays(route: list[tuple[float, float]], stops: list[dict[str, Any]],
                   avoid_areas: list[dict[str, Any]]) -> list[str]:
    """HERE Map Image v3 compact overlays: avoided areas, the route (flexible polyline) and
    labelled stops. `route` is (lon, lat) like GeoJSON; stops/areas come from B's constraints."""
    out = []
    for area in avoid_areas:
        geom = area["geometry"]
        rings = [geom["coordinates"][0]] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
        style = ORDER_ZONE_STYLE if area.get("kind") == "ORDER_ZONE" else CLOSURE_STYLE
        for ring in rings:
            out.append("polygon:" + ",".join(f"{lat:.5f},{lon:.5f}" for lon, lat in ring) + ";" + style)
    out.append("line:" + flexpolyline.encode([(lat, lon) for lon, lat in route], precision=5) + ";" + ROUTE_STYLE)
    labels = {"VOLUNTEER_START": "Start", "PICKUP": "Pickup", "SHELTER": "Shelter"}
    out.append("point:" + "|".join(f"{s['lat']:.5f},{s['lon']:.5f};label={labels.get(s.get('kind'), 'Stop')}"
                                   for s in stops) + "|size=small")
    return out


async def fetch_map_png(overlays: list[str], size: str = "640x400", api_key: str | None = None,
                        transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """One HERE Map Image call (server-side: the key never leaves this process)."""
    key = api_key if api_key is not None else os.getenv("HERE_API_KEY", "").strip()
    async with httpx.AsyncClient(transport=transport, timeout=20) as client:
        resp = await client.get(MAP_IMAGE_URL.format(size=size), params=[("apiKey", key)] +
                                [("overlay", o) for o in overlays])
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"HERE map image failed: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.content

LOCAL_TEST_URL = "http://127.0.0.1:8765/doorstep_test.png"  # served by `python -m http.server 8765`
WEB_TEST_URL = "https://res.cloudinary.com/demo/image/upload/sample.jpg"  # public demo image (HTTP 200)


def tiny_png(width: int = 160, height: int = 90, rgb: tuple[int, int, int] = (40, 120, 220)) -> bytes:
    """A solid-colour PNG (no dependencies), for the data: URI probe."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def image_test_card(variant: str) -> Card | str:
    """Dev probe: one detail card whose hero_image is a public https URL, a data: URI or a
    localhost URL (rendered only if the viewer's own browser fetches it)."""
    urls = {"web": WEB_TEST_URL, "data": data_uri(tiny_png()), "local": LOCAL_TEST_URL, "plain": ""}
    if variant not in urls:
        return "Dev: send 'test image web', 'test image data', 'test image local' or 'test image plain'."
    rows = [_row("Variant", variant), _row("URL kind", urls[variant][:60] + ("..." if len(urls[variant]) > 60 else "")),
            _row("Check", "Is there an image above these rows?"), _footer(None, "Doorstep dev image probe")]
    payload = {"title": f"{SIM_PREFIX} · Image test ({variant})", "summary_rows": rows,
               "ctas": [{"label": "OK", "primary": True, "selection": {"action": "image_test_ok"}}]}
    if urls[variant]:
        payload["hero_image"] = urls[variant]
    return Card("detail", payload, f"Dev image probe ({variant}). If the card shows a picture, this URL kind works.")

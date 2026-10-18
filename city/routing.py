"""Взима пешеходен маршрут A -> B. Само стандартна библиотека (urllib), без ключове за 'osm'."""
import json
import logging
import urllib.parse
import urllib.request
from functools import lru_cache

from django.conf import settings

log = logging.getLogger(__name__)
UA = {"User-Agent": "MyAbilityPath-hackathon/1.0"}


def _get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=settings.ROUTING_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def decode_polyline(encoded):
    """Google 'encoded polyline' -> [[lat, lng], ...]"""
    pts, i, lat, lng = [], 0, 0, 0
    while i < len(encoded):
        for which in ("lat", "lng"):
            shift = result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == "lat":
                lat += delta
            else:
                lng += delta
        pts.append([lat / 1e5, lng / 1e5])
    return pts


def parse_osrm(data):
    """OSRM (OpenStreetMap) отговор -> [[lat, lng], ...]"""
    coords = data["routes"][0]["geometry"]["coordinates"]       # [[lng, lat], ...]
    return [[c[1], c[0]] for c in coords]


def parse_google(data):
    return decode_polyline(data["routes"][0]["overview_polyline"]["points"])


def _osm(a, b):
    # Забележка: на routing.openstreetmap.de профилът се избира от пътя "routed-foot",
    # а думата след /v1/ е формалност.
    url = ("https://routing.openstreetmap.de/routed-foot/route/v1/driving/"
           f"{a[1]},{a[0]};{b[1]},{b[0]}?overview=full&geometries=geojson")
    return parse_osrm(_get_json(url))


def _google(a, b):
    q = urllib.parse.urlencode({
        "origin": f"{a[0]},{a[1]}", "destination": f"{b[0]},{b[1]}",
        "mode": "walking", "key": settings.GOOGLE_MAPS_API_KEY,
    })
    data = _get_json("https://maps.googleapis.com/maps/api/directions/json?" + q)
    if data.get("status") != "OK":
        raise RuntimeError(data.get("status"))
    return parse_google(data)


def _post_json(url, body, headers):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={**UA, **headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=settings.ROUTING_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ors(a, b, avoid=None):
    body = {"coordinates": [[a[1], a[0]], [b[1], b[0]]]}
    if avoid:
        body["options"] = {"avoid_polygons": avoid}
    data = _post_json(
        f"https://api.openrouteservice.org/v2/directions/{settings.ORS_PROFILE}/geojson",
        body, {"Authorization": settings.ORS_API_KEY})
    coords = data["features"][0]["geometry"]["coordinates"]
    return [[c[1], c[0]] for c in coords]


def _mock(a, b):
    return [list(a), list(b)]


@lru_cache(maxsize=1024)
def _cached(provider, a, b):
    if provider == "osm":
        return _osm(a, b)
    if provider == "google":
        return _google(a, b)
    if provider == "ors":
        return _ors(a, b)
    return _mock(a, b)


def get_route(a, b):
    """Връща (точки, източник). Ако услугата не работи -> права линия (source='mock')."""
    a = (round(a[0], 5), round(a[1], 5))
    b = (round(b[0], 5), round(b[1], 5))
    provider = settings.ROUTING_PROVIDER
    try:
        pts = _cached(provider, a, b)
        if len(pts) >= 2:
            return pts, provider
    except Exception as exc:  # мрежа, лимит, грешен ключ...
        log.warning("Routing '%s' failed: %s - fallback to straight line", provider, exc)
    return _mock(a, b), "mock"


@lru_cache(maxsize=256)
def ors_avoiding(a, b, polygon_key):
    """ORS маршрут, който не минава през дадените многоъгълници. polygon_key = tuple от пръстени."""
    polys = [[[[lng, lat] for lat, lng in ring]] for ring in polygon_key]
    geo = {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else \
          {"type": "MultiPolygon", "coordinates": polys}
    return _ors(a, b, geo)

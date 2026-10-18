"""Фейк препятствие: пътят, по който Гошо заобикаля 🚧.

Ред на опитите:
1. ORS с avoid_polygons - истинско заобикаляне по улиците (нужен е ORS_API_KEY).
2. Междинна точка встрани от препятствието: маршрут A->V + V->B през същата маршрутна услуга
   (работи и с OSM, и с Google). Пробваме няколко отстояния вляво/вдясно и взимаме най-краткия,
   който не минава през препятствието.
3. Схематична "гърбица" около препятствието - ако няма мрежа. Минава през сгради, но демото работи.
"""
import logging
from math import cos, radians

from django.conf import settings

from .analysis import densify, dist_m, distance_to_polyline, length_m
from .routing import get_route, ors_avoiding

log = logging.getLogger(__name__)
M_PER_DEG = 111320.0


def _offset(p, east_m, north_m):
    return (p[0] + north_m / M_PER_DEG, p[1] + east_m / (M_PER_DEG * cos(radians(p[0]))))


def _circle(c, r, n=12):
    from math import pi, sin
    ring = [_offset(c, r * cos(2 * pi * k / n), r * sin(2 * pi * k / n)) for k in range(n)]
    ring.append(ring[0])
    return tuple((round(a, 6), round(b, 6)) for a, b in ring)


def _clearance(path, obstacles):
    return min((distance_to_polyline(o[0], o[1], path) for o in obstacles), default=float("inf"))


def _on_route(route, obstacles):
    """Препятствията, които наистина са върху маршрута, подредени по реда, в който Гошо ги среща."""
    r = densify(route, 5)
    hits = []
    for o in obstacles:
        d = distance_to_polyline(o[0], o[1], route)
        if d <= settings.OBSTACLE_ON_ROUTE_M:
            i = min(range(len(r)), key=lambda k: dist_m(r[k], o))
            hits.append((i, o))
    return [o for _, o in sorted(hits)], r


def _trim_spur(leg1, leg2):
    """Маха 'отиди до междинната точка и се върни' на мястото, където двете части се свързват."""
    leg1, leg2 = densify(leg1, 5), densify(leg2, 5)
    while len(leg1) > 2 and len(leg2) > 2 and dist_m(leg1[-2], leg2[1]) < 8:
        leg1.pop()
        leg2.pop(0)
    return leg1 + leg2[1:]


def _normal_at(r, o):
    i = min(range(len(r)), key=lambda k: dist_m(r[k], o))
    p, q = r[max(0, i - 4)], r[min(len(r) - 1, i + 4)]
    lat0 = o[0]
    dx = (q[1] - p[1]) * M_PER_DEG * cos(radians(lat0))
    dy = (q[0] - p[0]) * M_PER_DEG
    n = (dx * dx + dy * dy) ** 0.5 or 1
    return -dy / n, dx / n, dx / n, dy / n           # нормала (изток, север) + посока


def _via(a, b, base, obstacles, first, r):
    nx, ny, _, _ = _normal_at(r, first)
    need = settings.OBSTACLE_RADIUS_M + 5
    best = None
    for d in (60, 100, 150, 220):
        for side in (1, -1):
            v = _offset(first, side * nx * d, side * ny * d)
            leg1, s1 = get_route(a, v)
            leg2, s2 = get_route(v, b)
            if "mock" in (s1, s2):
                return None
            path = _trim_spur(leg1, leg2)
            if _clearance(path, obstacles) < need:
                continue
            ln = length_m(path)
            if ln > 3 * length_m(base) + 300:
                continue
            if best is None or ln < best[0]:
                best = (ln, path)
        if best:
            return best[1]
    return None


def _bump(base, first):
    """Схематично заобикаляне (триъгълник): излиза встрани ~50 м преди препятствието и се връща ~50 м след него."""
    r = densify(base, 5)
    i = min(range(len(r)), key=lambda k: dist_m(r[k], first))
    acc, lo = 0.0, i
    while lo > 0 and acc < 50:
        acc += dist_m(r[lo - 1], r[lo]); lo -= 1
    acc, hi = 0.0, i
    while hi < len(r) - 1 and acc < 50:
        acc += dist_m(r[hi], r[hi + 1]); hi += 1
    nx, ny, _, _ = _normal_at(r, first)
    side = 45
    out = r[:lo + 1]
    out.append(_offset(first, nx * side, ny * side))
    out += r[hi:]
    return out


def get_detour(a, b, obstacles):
    """Връща dict: base (предложения маршрут), path (пътя на Гошо), method, source."""
    base, source = get_route(a, b)
    on_route, r = _on_route(base, obstacles)
    if not on_route:
        return {"base": base, "path": base, "method": "none", "source": source, "blocked": 0}
    out = {"base": base, "source": source, "blocked": len(on_route)}

    if settings.ROUTING_PROVIDER == "ors" and settings.ORS_API_KEY and source == "ors":
        try:
            key = tuple(_circle(o, settings.OBSTACLE_RADIUS_M) for o in on_route)
            path = ors_avoiding((round(a[0], 5), round(a[1], 5)), (round(b[0], 5), round(b[1], 5)), key)
            if len(path) >= 2:
                return {**out, "path": path, "method": "ors_avoid"}
        except Exception as exc:
            log.warning("ORS avoid_polygons failed: %s", exc)

    if source != "mock":
        path = _via(a, b, base, on_route, on_route[0], r)
        if path:
            return {**out, "path": path, "method": "via"}

    path = base
    for o in on_route:
        path = _bump(path, o)
    return {**out, "path": path, "method": "sketch"}

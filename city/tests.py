"""python manage.py test city - проверява откриването на заобикаляне върху синтетична улична мрежа
(улици през 100 м), без интернет и без маршрутна услуга."""
import heapq
import json
import math
from unittest import mock

from django.test import TestCase

from . import analysis, detour
from .models import Report

LAT0, LNG0 = 42.69, 23.32
K = 111320 * math.cos(math.radians(LAT0))


def ll(x, y):
    return (LAT0 + y / 111320, LNG0 + x / K)


def xy(p):
    return ((p[1] - LNG0) * K, (p[0] - LAT0) * 111320)


def on_street(x, y):
    return abs(x % 100) < 1e-6 or abs(y % 100) < 1e-6


def grid_route(a, b):
    """Най-кратък път по мрежа от улици през 100 м (като истинска маршрутна услуга)."""
    def snap(p):
        x, y = (round(v / 10) * 10 for v in xy(p))
        if on_street(x, y):
            return (x, y)
        nx, ny = round(x / 100) * 100, round(y / 100) * 100
        return (nx, y) if abs(nx - x) <= abs(ny - y) else (x, ny)
    s, t = snap(a), snap(b)
    dist, prev, pq = {s: 0}, {}, [(0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == t:
            break
        if d > dist[u]:
            continue
        for dx, dy in ((10, 0), (-10, 0), (0, 10), (0, -10)):
            v = (u[0] + dx, u[1] + dy)
            if -300 <= v[0] <= 800 and -300 <= v[1] <= 300 and on_street(*v) and d + 10 < dist.get(v, 1e9):
                dist[v], prev[v] = d + 10, u
                heapq.heappush(pq, (d + 10, v))
    path = [t]
    while path[-1] != s:
        path.append(prev[path[-1]])
    return [list(ll(*q)) for q in reversed(path)], "grid"


def minutes(path, m=60):
    path, out, s, acc = analysis.densify(path, 10), [], 0, 0
    for i in range(1, len(path)):
        acc += analysis.dist_m(path[i - 1], path[i])
        if acc >= m:
            out.append(path[s:i + 1]); s, acc = i, 0
    if s < len(path) - 1:
        out.append(path[s:])
    return out


STRAIGHT = [ll(x, 0) for x in range(0, 501, 10)]
DETOUR = ([ll(x, 0) for x in range(0, 201, 10)] + [ll(200, y) for y in range(10, 101, 10)] +
          [ll(x, 100) for x in range(210, 301, 10)] + [ll(300, y) for y in range(90, -1, -10)] +
          [ll(x, 0) for x in range(310, 501, 10)])


@mock.patch.object(analysis, "get_route", grid_route)
@mock.patch.object(detour, "get_route", grid_route)
class TrackingTests(TestCase):
    def walk(self, user, trip, path):
        res, mins = [], minutes(path)
        for i, ch in enumerate(mins):
            r = self.client.post("/api/segment/", json.dumps(
                {"user_id": user, "trip_id": trip, "idx": i, "path": ch, "final": i == len(mins) - 1}),
                content_type="application/json").json()
            res.append(r)
        return res

    def test_old_method_misses_detour(self):
        """Причината за бъга: всяка минута поотделно винаги 'съвпада'."""
        same = [analysis.compare_paths(c, grid_route(c[0], c[-1])[0])["same"] for c in minutes(DETOUR)]
        self.assertTrue(all(same))

    def test_straight_walk_is_same(self):
        self.assertFalse(any(r.get("deviation") for r in self.walk("u", "t", STRAIGHT)))

    def test_detour_detected_once_at_obstacle(self):
        devs = [r for r in self.walk("u", "t", DETOUR) if r.get("deviation")]
        self.assertEqual(len(devs), 1)
        x, y = xy(devs[0]["point"])
        self.assertLess(abs(x - 250) + abs(y), 30)     # препятствието е при x=250
        self.assertTrue(devs[0]["ask_survey"])

    def test_three_users_activate_problem(self):
        for u in ("a", "b", "c"):
            self.walk(u, "t-" + u, DETOUR)
        r = Report.objects.get(source="auto")
        self.assertEqual((r.status, r.deviation_users), ("active", 3))

    def test_gps_noise_ignored(self):
        import random
        random.seed(1)
        noisy = [ll(x + random.uniform(-6, 6), random.uniform(-10, 10)) for x in range(0, 601, 15)]
        self.assertFalse(any(r.get("deviation") for r in self.walk("n", "n", noisy)))

    def test_equal_alternative_ignored(self):
        alt = [ll(0, y) for y in range(0, 101, 10)] + [ll(x, 100) for x in range(10, 101, 10)]
        self.assertFalse(any(r.get("deviation") for r in self.walk("e", "e", alt)))

    def test_detour_avoids_obstacle(self):
        res = detour.get_detour(ll(0, 0), ll(500, 0), [ll(250, 3)])
        self.assertEqual(res["method"], "via")
        self.assertGreater(detour._clearance(res["path"], [ll(250, 0)]), 20)

    def test_confirm_and_deny(self):
        r = Report.objects.create(lat=LAT0, lng=LNG0, type="ramp", level="high")
        self.client.post(f"/api/reports/{r.pk}/confirm/", json.dumps({"still_there": True}), content_type="application/json")
        self.client.post(f"/api/reports/{r.pk}/confirm/", json.dumps({"still_there": False}), content_type="application/json")
        r.refresh_from_db()
        self.assertEqual((r.confirmations, r.denials), (1, 1))

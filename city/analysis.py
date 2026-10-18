"""Умната част: сравнение на пътя на Гошо с предложения маршрут и групиране на отклоненията в проблеми.

Защо не сравняваме всяка минута поотделно: краищата A и B на една минута са върху реалния път
на Гошо, така че най-краткият маршрут A->B почти винаги е точно неговият път ("маршрутът съвпада").
Заобикалянето се вижда чак когато прозорецът съдържа и излизането от улицата, и връщането обратно.
Затова всяка минута сравняваме ПЛЪЗГАЩ ПРОЗОРЕЦ от последните WINDOW_MINUTES минути:
A = checkpoint-ът преди WINDOW_MINUTES минути, B = текущата локация.
"""
import time
from collections import Counter
from math import cos, floor, radians

from django.conf import settings
from django.db.models import Avg, Count

from .models import SEVERITY_WEIGHT, Answer, Deviation, Report, Segment
from .routing import get_route

EARTH_R = 6371000.0


# ---------- геометрия (равнинна проекция, достатъчно точна за градски разстояния) ----------

def _xy(lat, lng, lat0):
    return radians(lng) * EARTH_R * cos(radians(lat0)), radians(lat) * EARTH_R


def _point_segment_distance(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def distance_to_polyline(lat, lng, points):
    """Разстояние в метри от точка до линия."""
    if not points:
        return float("inf")
    p = _xy(lat, lng, lat)
    xy = [_xy(a, b, lat) for a, b in points]
    if len(xy) == 1:
        return _point_segment_distance(p, xy[0], xy[0])
    return min(_point_segment_distance(p, xy[i], xy[i + 1]) for i in range(len(xy) - 1))


def dist_m(p, q):
    x1, y1 = _xy(p[0], p[1], p[0])
    x2, y2 = _xy(q[0], q[1], p[0])
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def length_m(points):
    return sum(dist_m(a, b) for a, b in zip(points, points[1:]))


def densify(points, step=10.0):
    """Добавя точки на всеки ~10 м, за да сравняваме равномерно."""
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(dist_m(a, b) // step))
        for k in range(1, n + 1):
            t = k / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def join_paths(parts):
    """Слепва минутите в един път (краят на едната минута = началото на следващата)."""
    out = []
    for part in parts:
        for p in part:
            p = (float(p[0]), float(p[1]))
            if not out or dist_m(out[-1], p) > 0.5:
                out.append(p)
    return out


# ---------- сравнение ----------

def _first_run(flags):
    """Индекси [i, j) на първата поредица от True."""
    i = next((k for k, f in enumerate(flags) if f), None)
    if i is None:
        return None
    j = i
    while j < len(flags) and flags[j]:
        j += 1
    return i, j


def compare_paths(user_path, route):
    """Сравнява пътя на човека с предложения маршрут.

    user_off_m  - метри от пътя на човека ИЗВЪН коридора около маршрута
    route_off_m - метри от маршрута, които човекът НЕ е минал
    extra_m     - с колко метра пътят на човека е по-дълъг от маршрута

    Мерим в метри, а не в проценти: при дълъг прозорец (8 мин ~ 480 м) едно заобикаляне на
    50-100 м иначе се "разтваря" под прага.
    Отклонение = формата е различна (OFF_ROUTE_MIN_M) И човекът е вървял поне DETOUR_MIN_EXTRA_M
    повече. Втората проверка филтрира равностойни алтернативи (обиколил е карето от другата страна)
    и GPS шум - заобикалянето на препятствие винаги удължава пътя.
    """
    corridor, step = settings.ON_ROUTE_METERS, 10.0
    u, r = densify(user_path, step), densify(route, step)
    u_d = [distance_to_polyline(p[0], p[1], route) for p in u]
    r_d = [distance_to_polyline(p[0], p[1], user_path) for p in r]
    u_len, r_len = length_m(user_path), length_m(route)
    user_off = u_len * sum(d > corridor for d in u_d) / len(u_d)
    route_off = r_len * sum(d > corridor for d in r_d) / len(r_d)
    extra = u_len - r_len
    shape_same = user_off < settings.OFF_ROUTE_MIN_M and route_off < settings.OFF_ROUTE_MIN_M
    deviation = (not shape_same) and extra >= settings.DETOUR_MIN_EXTRA_M

    point = checkpoint = None
    if deviation:
        run = _first_run([d > corridor for d in r_d])
        if run:
            # частта от маршрута, която Гошо е пропуснал: препятствието е някъде по нея
            i, j = run
            skipped = r[i:j]
            half, acc, point = length_m(skipped) / 2, 0.0, skipped[0]
            for a, b in zip(skipped, skipped[1:]):
                acc += dist_m(a, b)
                if acc >= half:
                    point = b
                    break
            checkpoint = r[max(0, i - 1)]          # последната точка, в която е бил на маршрута
        else:
            k = next(i for i, d in enumerate(u_d) if d > corridor)
            checkpoint = u[max(0, k - 1)]
            point = min(r, key=lambda q: dist_m(u[k], q))
    return {
        "same": not deviation, "shape_same": shape_same, "deviation": deviation,
        "user_off_m": round(user_off), "route_off_m": round(route_off),
        "extra_m": round(extra), "max_dist": round(max(u_d)),
        "point": list(point) if point else None,
        "checkpoint": list(checkpoint) if checkpoint else None,
    }


# ---------- групиране в проблеми (MAP анализ) ----------

def cell_key(lat, lng):
    s = settings.CELL_SIZE_DEG
    return f"{floor(lat / s)}_{floor(lng / s)}"


def nearest_auto_cell(lat, lng):
    """Отклонения до MERGE_METERS от вече засечен проблем се залепват към него."""
    best = None
    for r in Report.objects.filter(source="auto").exclude(cell=""):
        d = dist_m((lat, lng), (r.lat, r.lng))
        if d <= settings.MERGE_METERS and (best is None or d < best[0]):
            best = (d, r.cell)
    return best[1] if best else None


def recompute_cell(cell):
    """Преброява колко РАЗЛИЧНИ хора са се отклонили в клетката и обновява проблема."""
    agg = Deviation.objects.filter(cell=cell).aggregate(
        lat=Avg("lat"), lng=Avg("lng"), users=Count("user_id", distinct=True)
    )
    if not agg["users"]:
        return None
    report = Report.objects.filter(cell=cell, source="auto").first()
    if report is None:
        report = Report(cell=cell, source="auto", type="other", level="none")
    report.lat, report.lng = agg["lat"], agg["lng"]
    report.deviation_users = agg["users"]
    report.status = "active" if agg["users"] >= settings.MIN_USERS else "candidate"
    report.save()
    return report


def recompute_all():
    cells = Deviation.objects.values_list("cell", flat=True).distinct()
    return [r for r in (recompute_cell(c) for c in cells) if r]


def apply_answers(report):
    """Отговорите от въпросника -> тип (най-често посочения) + ниво (най-сериозното)."""
    answers = [a for a in report.answers.all() if not a.skipped]
    if not answers:
        return report
    types = Counter(a.type for a in answers if a.type != "other")
    if types:
        report.type = types.most_common(1)[0][0]
    report.level = max((a.level for a in answers), key=lambda l: SEVERITY_WEIGHT[l] if l != "none" else 0)
    report.save()
    return report


# ---------- една минута следене ----------

def window_segments(trip_id, idx):
    """Минутите, които влизат в прозореца, завършващ с минута idx.
    Не прескачаме назад през вече засечено отклонение - иначе едно заобикаляне се брои многократно."""
    last_dev = (Segment.objects.filter(trip_id=trip_id, deviation=True, idx__lt=idx)
                .order_by("-idx").values_list("idx", flat=True).first())
    lo = max(idx - settings.WINDOW_MINUTES + 1, (last_dev + 1) if last_dev is not None else 0)
    return list(Segment.objects.filter(trip_id=trip_id, idx__gte=lo, idx__lte=idx).order_by("idx"))


def analyse_minute(seg, final=False):
    """seg е току-що записаната минута. Сравняваме прозореца, който завършва с нея.

    Едно различно сравнение е само подозрение. Записваме отклонение, когато заобикалянето е
    завършило: прозорецът пак се различава, но допълнителните метри вече не растат (Гошо се е
    върнал на маршрута, затова и мястото на препятствието е най-точно). Също и в края на пътуването
    или ако подозрението продължава прекалено дълго."""
    segs = window_segments(seg.trip_id, seg.idx)
    window = join_paths(s.path for s in segs)
    result = {"idx": seg.idx, "window_from": segs[0].idx, "window": window,
              "deviation": False, "ask_survey": False}
    if len(window) < 2 or dist_m(window[0], window[-1]) < 10:
        result.update(skipped=True, same=True)
        return result

    t0 = time.perf_counter()
    route, source = get_route(window[0], window[-1])
    result["route_ms"] = round((time.perf_counter() - t0) * 1000)
    cmp = compare_paths(window, route)
    seg.window_from, seg.route, seg.route_source = segs[0].idx, route, source
    seg.same, seg.extra_m, seg.deviation = cmp["same"], cmp["extra_m"], False
    seg.save()
    result.update(route=route, route_source=source, **{k: cmp[k] for k in
                  ("same", "shape_same", "user_off_m", "route_off_m", "extra_m")})
    if not cmp["deviation"]:
        return result
    prev = Segment.objects.filter(trip_id=seg.trip_id, idx=seg.idx - 1).first()
    streak = 0
    for s in reversed(segs[:-1]):                 # колко поредни минути вече е "подозрение"
        if s.route is None or s.same or s.deviation:
            break
        streak += 1
    settled = streak > 0 and prev is not None and cmp["extra_m"] <= prev.extra_m + 10
    confirmed = final or settled or streak >= settings.WINDOW_MINUTES // 2
    if not confirmed:
        seg.deviation = False
        seg.save()
        result.update(suspect=True)
        return result
    seg.deviation = True
    seg.save()

    lat, lng = cmp["point"]
    cell = nearest_auto_cell(lat, lng) or cell_key(lat, lng)
    Deviation.objects.create(
        user_id=seg.user_id, trip_id=seg.trip_id, lat=lat, lng=lng, cell=cell,
        cp_lat=cmp["checkpoint"][0], cp_lng=cmp["checkpoint"][1], distance_m=cmp["max_dist"])
    report = recompute_cell(cell)
    mine = Deviation.objects.filter(cell=cell, user_id=seg.user_id).count()
    already = Answer.objects.filter(report=report, user_id=seg.user_id).exists()
    result.update(deviation=True, point=cmp["point"], checkpoint=cmp["checkpoint"],
                  report_id=report.pk, status=report.status, users=report.deviation_users,
                  ask_survey=mine >= settings.SURVEY_AFTER_DEVIATIONS and not already)
    return result

import json

from django.conf import settings
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt  # за хакатон; за продукция - добавете токен
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from .analysis import analyse_minute, apply_answers, cell_key, dist_m
from .detour import get_detour
from .models import Answer, Deviation, Report, Segment
from .routing import get_route


def _body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _num(data, key):
    try:
        return float(data[key])
    except (KeyError, TypeError, ValueError):
        return None


def _tiles():
    return {"url": settings.TILE_URL, "attribution": settings.TILE_ATTRIBUTION, "max_zoom": settings.TILE_MAX_ZOOM}


def report_dict(r):
    return {
        "id": r.id, "lat": r.lat, "lng": r.lng,
        "type": r.type, "type_label": r.get_type_display(),
        "level": r.level, "level_label": r.get_level_display(),
        "source": r.source, "status": r.status,
        "confirmations": r.confirmations, "denials": r.denials, "deviation_users": r.deviation_users,
        "confidence": r.confidence, "priority": r.priority,
    }


# ---------- страници ----------

def index(request):
    """Екранът на Диди (телефон) + панелът на MAP до него на широк екран."""
    return render(request, "city/gosho.html", {
        "center": list(settings.DEMO_CENTER), "zoom": settings.DEMO_ZOOM,
        "walk_m": settings.WALK_METERS_PER_MINUTE, "min_users": settings.MIN_USERS,
        "window_min": settings.WINDOW_MINUTES,
        "demo_a": list(settings.DEMO_START), "demo_b": list(settings.DEMO_END),
        "demo_labels": [settings.DEMO_START_LABEL, settings.DEMO_END_LABEL],
        "provider": settings.ROUTING_PROVIDER, "tiles": _tiles(),
    })


@xframe_options_sameorigin                  # панелът се вгражда до телефона на /
def dashboard(request):
    """Екранът на MyAbility Path (MAP) - админите."""
    return render(request, "city/dashboard.html", {
        "center": list(settings.DEMO_CENTER), "zoom": settings.DEMO_ZOOM,
        "embed": request.GET.get("embed") == "1", "debug": settings.DEBUG,
        "min_users": settings.MIN_USERS, "tiles": _tiles(),
    })


# ---------- API ----------

@require_GET
def api_reports(request):
    qs = Report.objects.all()
    if request.GET.get("all") != "1":          # Диди вижда само активните
        qs = qs.filter(status="active")
    data = sorted((report_dict(r) for r in qs), key=lambda d: -d["priority"])
    stats = {
        "users": Segment.objects.values("user_id").distinct().count(),
        "segments": Segment.objects.count(),
        "bad_segments": Segment.objects.filter(same=False).count(),
        "deviations": Deviation.objects.count(),
    }
    return JsonResponse({"reports": data, "stats": stats})


@csrf_exempt
@require_POST
def api_report_create(request):
    d = _body(request)
    lat, lng = _num(d, "lat"), _num(d, "lng")
    if lat is None or lng is None:
        return JsonResponse({"error": "lat/lng"}, status=400)
    r = Report.objects.create(
        lat=lat, lng=lng, cell=cell_key(lat, lng), source="user", status="active",
        type=d.get("type") if d.get("type") in dict(Report.TYPES) else "other",
        level=d.get("level") if d.get("level") in dict(Report.LEVELS) else "none",
    )
    return JsonResponse(report_dict(r), status=201)


@csrf_exempt
@require_POST
def api_confirm(request, pk):
    """Диди потвърждава вече съществуващ репорт: {"still_there": true} = да, false = вече го няма."""
    r = get_object_or_404(Report, pk=pk)
    still_there = _body(request).get("still_there", True) is not False
    field = "confirmations" if still_there else "denials"
    Report.objects.filter(pk=pk).update(**{field: F(field) + 1})
    r.refresh_from_db()
    return JsonResponse(report_dict(r))


def _path(raw):
    """Проверка на списък от [lat, lng] точки."""
    if not isinstance(raw, list) or not (2 <= len(raw) <= 300):
        return None
    out = []
    for p in raw:
        try:
            out.append((float(p[0]), float(p[1])))
        except (TypeError, ValueError, IndexError):
            return None
    return out


@csrf_exempt
@require_POST
def api_segment(request):
    """Една 'минута' следене: точките на Диди от последния checkpoint до сега.
    Записваме минутата и сравняваме плъзгащия прозорец от последните WINDOW_MINUTES минути."""
    d = _body(request)
    path, uid = _path(d.get("path")), str(d.get("user_id", ""))[:64]
    if not path or not uid:
        return JsonResponse({"error": "user_id/path"}, status=400)
    trip = str(d.get("trip_id") or f"trip-{uid}")[:64]
    try:
        idx = int(d.get("idx"))
    except (TypeError, ValueError):
        idx = Segment.objects.filter(trip_id=trip).count()
    seg, _ = Segment.objects.update_or_create(
        trip_id=trip, idx=idx,
        defaults=dict(user_id=uid, path=[list(p) for p in path], a_lat=path[0][0], a_lng=path[0][1],
                      b_lat=path[-1][0], b_lng=path[-1][1], same=True, deviation=False))
    return JsonResponse(analyse_minute(seg, final=bool(d.get("final"))))


@csrf_exempt
@require_POST
def api_warm(request):
    """Загрява кеша на маршрутите за двойки A->B, които знаем, че ще поискаме (авто демото).
    Пита маршрутната услуга по 4 наведнъж, за да не чака Диди на всеки checkpoint."""
    from concurrent.futures import ThreadPoolExecutor
    pairs = []
    for raw in (_body(request).get("pairs") or [])[:40]:
        ab = _path(raw)
        if ab:
            pairs.append(ab)
    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = list(pool.map(lambda ab: get_route(ab[0], ab[1])[1], pairs))
    return JsonResponse({"warmed": len(pairs), "sources": sorted(set(sources))})


@csrf_exempt
@require_POST
def api_detour(request):
    """Фейк препятствие: пътят, по който Диди заобикаля 🚧 между a и b."""
    d = _body(request)
    ab = _path([d.get("a"), d.get("b")])
    raw = d.get("obstacles") or []
    obstacles = _path(raw + raw) if isinstance(raw, list) and raw else []   # _path иска >= 2 точки
    if not ab or obstacles is None:
        return JsonResponse({"error": "a/b/obstacles"}, status=400)
    return JsonResponse(get_detour(ab[0], ab[1], obstacles[:len(raw)][:10]))


@require_GET
def api_trip(request, trip_id):
    """Всичко за едно пътуване - за анализа в панела."""
    segs = list(Segment.objects.filter(trip_id=trip_id).order_by("idx"))
    devs = list(Deviation.objects.filter(trip_id=trip_id))
    uid = segs[0].user_id if segs else ""
    cells = {d.cell for d in devs}
    reports = [report_dict(r) for r in Report.objects.filter(cell__in=cells, source="auto")]
    answers = {a.report_id: {"skipped": a.skipped, "type": a.get_type_display(), "level": a.get_level_display()}
               for a in Answer.objects.filter(user_id=uid, report__cell__in=cells)}
    for r in reports:
        r["answer"] = answers.get(r["id"])
    dev_seg = next((s for s in segs if s.deviation), None)
    return JsonResponse({
        "trip_id": trip_id, "user_id": uid, "minutes": len(segs),
        "same_minutes": sum(1 for s in segs if s.route is not None and s.same),
        "path": [p for s in segs for p in s.path],
        "deviation_window": {"from": dev_seg.window_from, "to": dev_seg.idx, "route": dev_seg.route,
                             "extra_m": dev_seg.extra_m} if dev_seg else None,
        "deviations": [{"lat": d.lat, "lng": d.lng, "cp": [d.cp_lat, d.cp_lng] if d.cp_lat else None}
                       for d in devs],
        "reports": reports,
    })


@require_GET
def api_report_detail(request, pk):
    """Проблем + всички отклонения и отговори зад него (MAP анализ)."""
    r = get_object_or_404(Report, pk=pk)
    devs = Deviation.objects.filter(cell=r.cell) if r.source == "auto" else Deviation.objects.none()
    answers = list(r.answers.all())
    levels = {}
    for a in answers:
        key = "skipped" if a.skipped else a.level
        levels[key] = levels.get(key, 0) + 1
    return JsonResponse({
        **report_dict(r),
        "deviations": [{"lat": d.lat, "lng": d.lng, "cp": [d.cp_lat, d.cp_lng] if d.cp_lat else None,
                        "user": d.user_id[-4:]} for d in devs],
        "answers": {"total": len(answers), "by_level": levels},
    })


@csrf_exempt
@require_POST
def api_demo_reset(request):
    """Изчиства всички данни (само при DEBUG) - за репетиции на демото."""
    if not settings.DEBUG:
        return JsonResponse({"error": "disabled"}, status=403)
    for m in (Answer, Deviation, Segment, Report):
        m.objects.all().delete()
    return JsonResponse({"ok": True})


@require_GET
def api_route(request):
    """Предложеният пешеходен маршрут между две точки (за бутона 'По маршрута')."""
    try:
        a = (float(request.GET["alat"]), float(request.GET["alng"]))
        b = (float(request.GET["blat"]), float(request.GET["blng"]))
    except (KeyError, ValueError):
        return JsonResponse({"error": "alat/alng/blat/blng"}, status=400)
    route, source = get_route(a, b)
    return JsonResponse({"route": route, "route_source": source})


@csrf_exempt
@require_POST
def api_answer(request):
    """Отговор на въпросника (или 'пропусни')."""
    d = _body(request)
    r = get_object_or_404(Report, pk=d.get("report_id"))
    skipped = bool(d.get("skipped"))
    Answer.objects.update_or_create(
        report=r, user_id=str(d.get("user_id", ""))[:64],
        defaults={
            "skipped": skipped,
            "type": d.get("type") if d.get("type") in dict(Report.TYPES) else "other",
            "level": d.get("level") if d.get("level") in dict(Report.LEVELS) else "none",
        },
    )
    apply_answers(r)
    r.refresh_from_db()
    return JsonResponse(report_dict(r))

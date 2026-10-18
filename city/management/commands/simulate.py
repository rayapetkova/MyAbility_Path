"""python manage.py simulate [--reset]
Демо данни БЕЗ интернет: няколко ръчни репорта + 10 'потребители', 6 от които са се отклонили на едно и също място."""
import random

from django.conf import settings
from django.core.management.base import BaseCommand

from city.analysis import cell_key, recompute_all
from city.models import Answer, Deviation, Report, Segment


class Command(BaseCommand):
    help = "Генерира демо данни за презентацията"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="изтрива старите данни първо")

    def handle(self, *args, **opts):
        random.seed(7)
        if opts["reset"]:
            for m in (Answer, Deviation, Segment, Report):
                m.objects.all().delete()

        lat0, lng0 = settings.DEMO_CENTER
        if not Report.objects.filter(source="user").exists():
            Report.objects.create(lat=lat0 + 0.0010, lng=lng0 - 0.0018, cell="m1", type="ramp", level="high", confirmations=4)
            Report.objects.create(lat=lat0 - 0.0006, lng=lng0 + 0.0012, cell="m2", type="stairs", level="mid", confirmations=2)
            Report.objects.create(lat=lat0 + 0.0008, lng=lng0 + 0.0030, cell="m3", type="narrow", level="low", confirmations=1)

        obstacle = (lat0 + 0.0004, lng0 + 0.0002)      # "препятствието" е близо до центъра
        for u in range(10):
            uid = f"demo-user-{u}"
            for _ in range(5):                           # няколко 'минути' следене на човек
                a = (lat0 + random.uniform(-.001, .001), lng0 + random.uniform(-.001, .001))
                Segment.objects.create(user_id=uid, a_lat=a[0], a_lng=a[1], b_lat=a[0] + .0004, b_lng=a[1] + .0004,
                                       same=True, route_source="demo")
            if u < 6:                                    # 6 от 10 заобикалят препятствието
                la = obstacle[0] + random.uniform(-.00008, .00008)
                ln = obstacle[1] + random.uniform(-.00008, .00008)
                Segment.objects.create(user_id=uid, a_lat=la, a_lng=ln, b_lat=la, b_lng=ln, same=False, route_source="demo")
                Deviation.objects.create(user_id=uid, lat=la, lng=ln, cell=cell_key(*obstacle), distance_m=45)
        recompute_all()
        self.stdout.write(self.style.SUCCESS(
            f"Готово: {Report.objects.count()} проблема, {Deviation.objects.count()} отклонения, {Segment.objects.count()} сегмента."))

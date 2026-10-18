"""python manage.py analyse - прерачунава всички проблеми от записаните отклонения."""
from django.core.management.base import BaseCommand

from city.analysis import recompute_all


class Command(BaseCommand):
    help = "MAP анализ: групира отклоненията в проблеми"

    def handle(self, *args, **opts):
        reports = recompute_all()
        active = sum(1 for r in reports if r.status == "active")
        self.stdout.write(self.style.SUCCESS(f"{len(reports)} проблема ({active} активни)"))

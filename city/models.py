from django.db import models

SEVERITY_WEIGHT = {"none": 1, "low": 1, "mid": 2, "high": 3}


class Report(models.Model):
    TYPES = [
        ("ramp", "Липсва рампа"),
        ("stairs", "Стълби"),
        ("narrow", "Тясно / блокирано"),
        ("other", "Друго / неизвестно"),
    ]
    LEVELS = [
        ("high", "Сериозен проблем"),
        ("mid", "Среден проблем"),
        ("low", "Лек проблем"),
        ("none", "Няма информация"),
    ]
    SOURCES = [("user", "Докладван от потребител"), ("auto", "Засечен автоматично")]
    STATUSES = [("candidate", "Кандидат (малко данни)"), ("active", "Активен")]

    lat = models.FloatField()
    lng = models.FloatField()
    cell = models.CharField(max_length=40, blank=True, db_index=True)
    type = models.CharField(max_length=10, choices=TYPES, default="other")
    level = models.CharField(max_length=5, choices=LEVELS, default="none")
    source = models.CharField(max_length=5, choices=SOURCES, default="user")
    status = models.CharField(max_length=10, choices=STATUSES, default="active")
    confirmations = models.PositiveIntegerField(default=0)
    denials = models.PositiveIntegerField(default=0)        # "Не, вече го няма"
    deviation_users = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    @property
    def confidence(self):
        """Колко сме сигурни, че проблемът е истински."""
        score = self.deviation_users + self.confirmations + (1 if self.source == "user" else 0)
        return max(0, score - self.denials)

    @property
    def priority(self):
        return self.confidence * SEVERITY_WEIGHT.get(self.level, 1)

    def __str__(self):
        return f"#{self.pk} {self.get_type_display()} ({self.get_level_display()})"


class Segment(models.Model):
    """Една 'минута' следене: от checkpoint A до B.
    same/deviation/route се отнасят за ПРОЗОРЕЦА window_from..idx, който завършва с тази минута."""
    user_id = models.CharField(max_length=64, db_index=True)
    trip_id = models.CharField(max_length=64, db_index=True, default="")
    idx = models.PositiveIntegerField(default=0)           # номер на минутата в пътуването
    path = models.JSONField(default=list)                  # точките на човека в тази минута
    a_lat = models.FloatField()
    a_lng = models.FloatField()
    b_lat = models.FloatField()
    b_lng = models.FloatField()
    same = models.BooleanField(default=True)
    deviation = models.BooleanField(default=False)
    window_from = models.PositiveIntegerField(null=True, blank=True)
    route = models.JSONField(null=True, blank=True)        # предложеният маршрут за прозореца
    extra_m = models.FloatField(default=0)                 # с колко метра човекът е вървял повече
    route_source = models.CharField(max_length=10, default="")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("trip_id", "idx")


class Deviation(models.Model):
    """Отклонение от предложения маршрут.
    cp_* = checkpoint-ът, в който е излязъл от маршрута; lat/lng = средата на пропуснатата част
    (там най-вероятно е препятствието; по нея групираме)."""
    user_id = models.CharField(max_length=64, db_index=True)
    trip_id = models.CharField(max_length=64, blank=True, default="")
    lat = models.FloatField()
    lng = models.FloatField()
    cp_lat = models.FloatField(null=True, blank=True)
    cp_lng = models.FloatField(null=True, blank=True)
    cell = models.CharField(max_length=40, db_index=True)
    distance_m = models.FloatField(default=0)
    created = models.DateTimeField(auto_now_add=True)


class Answer(models.Model):
    """Отговор на въпросника за конкретен проблем."""
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="answers")
    user_id = models.CharField(max_length=64)
    type = models.CharField(max_length=10, choices=Report.TYPES, default="other")
    level = models.CharField(max_length=5, choices=Report.LEVELS, default="none")
    skipped = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("report", "user_id")

from django.db import models

class Instrument(models.Model):
    name = models.CharField(max_length=100)
    ticker = models.CharField(max_length=10, unique=True)

    def __str__(self):
        return f"{self.ticker} ({self.name})"

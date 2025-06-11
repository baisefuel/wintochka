from django.db import models
from users.models import User

class Balance(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=10)
    amount = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'ticker')

    def __str__(self):
        return f"{self.user.name} — {self.ticker}: {self.amount}"

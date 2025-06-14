import uuid
from django.db import models
from users.models import User


class OrderStatus(models.TextChoices):
    NEW = "NEW"
    EXECUTED = "EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCELLED = "CANCELLED"


class Direction(models.TextChoices):
    BUY = "BUY"
    SELL = "SELL"


class BaseOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=10)
    qty = models.PositiveIntegerField()
    direction = models.CharField(max_length=4, choices=Direction.choices)
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.NEW)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class MarketOrder(BaseOrder):
    pass



class LimitOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=10)
    direction = models.CharField(max_length=4, choices=[("BUY", "BUY"), ("SELL", "SELL")])
    price = models.PositiveIntegerField()
    original_qty = models.PositiveIntegerField()
    filled = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=[
        ("NEW", "NEW"),
        ("EXECUTED", "EXECUTED"),
        ("PARTIALLY_EXECUTED", "PARTIALLY_EXECUTED"),
        ("CANCELLED", "CANCELLED")
    ], default=OrderStatus.NEW)
    timestamp = models.DateTimeField(auto_now_add=True)

    @property
    def remaining_qty(self):
        return self.original_qty - self.filled

class Transaction(models.Model):
    ticker = models.CharField(max_length=10)
    amount = models.PositiveIntegerField()
    price = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

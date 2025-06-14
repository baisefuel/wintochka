import logging
from uuid import UUID
from django.db import models
from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class OrderStatus:
    NEW = "NEW"
    EXECUTED = "EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCELLED = "CANCELLED"

    CHOICES = [
        (NEW, "NEW"),
        (EXECUTED, "EXECUTED"),
        (PARTIALLY_EXECUTED, "PARTIALLY_EXECUTED"),
        (CANCELLED, "CANCELLED")
    ]

class MarketOrder(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=16)
    direction = models.CharField(max_length=4, choices=[("BUY", "BUY"), ("SELL", "SELL")])
    qty = models.PositiveIntegerField()
    status = models.CharField(max_length=32, choices=OrderStatus.CHOICES)
    filled = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class LimitOrder(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=16)
    direction = models.CharField(max_length=4, choices=[("BUY", "BUY"), ("SELL", "SELL")])
    price = models.DecimalField(max_digits=20, decimal_places=4)
    original_qty = models.PositiveIntegerField()
    filled = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, choices=OrderStatus.CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

class Transaction(models.Model):
    ticker = models.CharField(max_length=16)
    amount = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=20, decimal_places=4)
    timestamp = models.DateTimeField(auto_now_add=True)

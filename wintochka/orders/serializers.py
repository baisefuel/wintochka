from rest_framework import serializers
from .models import Direction

class CreateOrderResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    user_id = serializers.UUIDField(source='user.id')
    ticker = serializers.CharField()
    direction = serializers.CharField()
    qty = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    filled = serializers.IntegerField(required=False)
    status = serializers.CharField()
    timestamp = serializers.DateTimeField()

class MarketOrderSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(choices=Direction.choices)
    ticker = serializers.CharField()
    qty = serializers.IntegerField(min_value=1)

class LimitOrderSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(choices=Direction.choices)
    ticker = serializers.CharField()
    qty = serializers.IntegerField(min_value=1)
    price = serializers.IntegerField(min_value=1)

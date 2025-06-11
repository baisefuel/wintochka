from rest_framework import serializers
from .models import Direction

class MarketOrderSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(choices=Direction.choices)
    ticker = serializers.CharField()
    qty = serializers.IntegerField(min_value=1)

class LimitOrderSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(choices=Direction.choices)
    ticker = serializers.CharField()
    qty = serializers.IntegerField(min_value=1)
    price = serializers.IntegerField(min_value=1)

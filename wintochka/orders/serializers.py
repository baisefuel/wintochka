from rest_framework import serializers
from .models import MarketOrder, LimitOrder

class MarketOrderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketOrder
        fields = ("ticker", "direction", "qty")

    def create(self, validated_data):
        return MarketOrder.objects.create(**validated_data, status=OrderStatus.NEW)


class LimitOrderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LimitOrder
        fields = ("ticker", "direction", "price", "original_qty")

    def create(self, validated_data):
        return LimitOrder.objects.create(**validated_data, status=OrderStatus.NEW, filled=0)


class OrderbookLevelSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=20, decimal_places=4)
    qty = serializers.IntegerField()


class OrderbookSerializer(serializers.Serializer):
    bids = OrderbookLevelSerializer(many=True)
    asks = OrderbookLevelSerializer(many=True)

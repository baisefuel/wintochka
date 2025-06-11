from uuid import UUID
from django.db import transaction
from django.db.models import Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import (
    MarketOrder,
    LimitOrder,
    OrderStatus,
    Transaction
)
from .serializers import MarketOrderSerializer, LimitOrderSerializer
from users.permissions import HasAPIKey
from users.utils import get_user_from_token
from balances.models import Balance


class OrderCreateView(APIView):
    permission_classes = [HasAPIKey]

    def post(self, request):
        user = get_user_from_token(request)
        data = request.data

        is_market = 'price' not in data
        serializer_class = MarketOrderSerializer if is_market else LimitOrderSerializer
        serializer = serializer_class(data=data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=422)

        validated = serializer.validated_data

        with transaction.atomic():
            if is_market:
                order = MarketOrder.objects.create(user=user, **validated, status=OrderStatus.EXECUTED)
                if validated["direction"] == "BUY":
                    cost = 1 * validated["qty"]
                    balance, _ = Balance.objects.get_or_create(user=user, ticker="USD")
                    if balance.amount < cost:
                        return Response({"error": "Недостаточно средств"}, status=400)
                    balance.amount -= cost
                    balance.save()
                else:  # SELL
                    balance, _ = Balance.objects.get_or_create(user=user, ticker=validated["ticker"])
                    if balance.amount < validated["qty"]:
                        return Response({"error": "Недостаточно монет"}, status=400)
                    balance.amount -= validated["qty"]
                    balance.save()

                Transaction.objects.create(
                    ticker=validated["ticker"],
                    amount=validated["qty"],
                    price=1
                )
            else:
                order = LimitOrder.objects.create(user=user, **validated)

        return Response({"success": True, "order_id": str(order.id)}, status=200)


class OrderListView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request):
        user = get_user_from_token(request)
        market_orders = MarketOrder.objects.filter(user=user)
        limit_orders = LimitOrder.objects.filter(user=user)

        def serialize(order):
            return {
                "id": str(order.id),
                "direction": order.direction,
                "ticker": order.ticker,
                "qty": order.qty,
                "status": order.status,
                "timestamp": order.timestamp.isoformat()
            } | ({"price": order.price, "filled": order.filled} if hasattr(order, 'price') else {})

        all_orders = list(map(serialize, market_orders)) + list(map(serialize, limit_orders))
        return Response(all_orders)


class OrderDetailCancelView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request, order_id):
        user = get_user_from_token(request)

        try:
            uuid_val = UUID(order_id)
        except ValueError:
            return Response({"error": "Invalid UUID"}, status=400)

        order = (
            MarketOrder.objects.filter(id=order_id, user=user).first() or
            LimitOrder.objects.filter(id=order_id, user=user).first()
        )
        if not order:
            return Response({"error": "Order not found"}, status=404)

        data = {
            "id": str(order.id),
            "direction": order.direction,
            "ticker": order.ticker,
            "qty": order.qty,
            "status": order.status,
            "timestamp": order.timestamp.isoformat()
        }
        if hasattr(order, "price"):
            data["price"] = order.price
            data["filled"] = order.filled

        return Response(data)

    def delete(self, request, order_id):
        user = get_user_from_token(request)
        order = LimitOrder.objects.filter(id=order_id, user=user, status="NEW").first()
        if not order:
            return Response({"error": "Only NEW limit orders can be cancelled or order not found"}, status=400)

        order.status = "CANCELLED"
        order.save()
        return Response({"success": True})


class OrderBookView(APIView):
    def get(self, request, ticker):
        limit = int(request.query_params.get("limit", 10))
        limit = min(limit, 25)

        orders = LimitOrder.objects.filter(ticker=ticker, status="NEW")

        bids = (
            orders.filter(direction="BUY")
            .values("price")
            .annotate(qty=Sum("qty"))
            .order_by("-price")[:limit]
        )
        asks = (
            orders.filter(direction="SELL")
            .values("price")
            .annotate(qty=Sum("qty"))
            .order_by("price")[:limit]
        )

        return Response({
            "bid_levels": list(bids),
            "ask_levels": list(asks),
        })


class TransactionHistoryView(APIView):
    def get(self, request, ticker):
        limit = int(request.query_params.get("limit", 10))
        limit = min(limit, 100)

        transactions = Transaction.objects.filter(ticker=ticker).order_by("-timestamp")[:limit]

        data = [
            {
                "ticker": t.ticker,
                "amount": t.amount,
                "price": t.price,
                "timestamp": t.timestamp.isoformat()
            }
            for t in transactions
        ]
        return Response(data)

import logging
from uuid import UUID
from django.db import transaction
from django.db.models import Sum, F, ExpressionWrapper, IntegerField
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from .models import MarketOrder, LimitOrder, OrderStatus, Transaction
from .serializers import (
    MarketOrderCreateSerializer,
    LimitOrderCreateSerializer,
    OrderbookSerializer
)
from users.permissions import HasAPIKey
from users.utils import get_user_from_token
from balances.models import Balance
from instruments.models import Instrument

logger = logging.getLogger(__name__)

class OrderMatchingEngine:
    @staticmethod
    def execute_trade(buy_order, sell_order, qty, price):
        with transaction.atomic():
            cost = qty * price

            buyer_rub = Balance.objects.select_for_update().get(user=buy_order.user, ticker="RUB")
            seller_asset = Balance.objects.select_for_update().get(user=sell_order.user, ticker=sell_order.ticker)

            if buyer_rub.amount < cost:
                raise ValidationError("Недостаточно средств у покупателя")
            if seller_asset.amount < qty:
                raise ValidationError("Недостаточно активов у продавца")

            seller_rub, _ = Balance.objects.get_or_create(user=sell_order.user, ticker="RUB")
            buyer_asset, _ = Balance.objects.get_or_create(user=buy_order.user, ticker=sell_order.ticker)

            buyer_rub.amount -= cost
            seller_asset.amount -= qty
            seller_rub.amount += cost
            buyer_asset.amount += qty

            buyer_rub.save()
            seller_asset.save()
            seller_rub.save()
            buyer_asset.save()

            Transaction.objects.create(ticker=sell_order.ticker, amount=qty, price=price)

            logger.info(f"Trade executed: {qty} {sell_order.ticker} @ {price} | buyer={buy_order.user.id}, seller={sell_order.user.id}")

    @staticmethod
    def match_order(order):
        logger.info(f"Matching started for order {order.id}")

        if isinstance(order, MarketOrder):
            if order.direction == "BUY":
                counter_orders = LimitOrder.objects.filter(ticker=order.ticker, direction="SELL", status="NEW").order_by("price", "created_at")
            else:
                counter_orders = LimitOrder.objects.filter(ticker=order.ticker, direction="BUY", status="NEW").order_by("-price", "created_at")
        else:
            if order.direction == "BUY":
                counter_orders = LimitOrder.objects.filter(ticker=order.ticker, direction="SELL", status="NEW", price__lte=order.price).order_by("price", "created_at")
            else:
                counter_orders = LimitOrder.objects.filter(ticker=order.ticker, direction="BUY", status="NEW", price__gte=order.price).order_by("-price", "created_at")

        total_filled = 0

        for counter_order in counter_orders:
            if order.filled >= order.original_qty:
                break

            fillable = min(order.original_qty - order.filled, counter_order.original_qty - counter_order.filled)
            if fillable <= 0:
                continue

            try:
                OrderMatchingEngine.execute_trade(
                    buy_order=order if order.direction == "BUY" else counter_order,
                    sell_order=counter_order if order.direction == "BUY" else order,
                    qty=fillable,
                    price=counter_order.price
                )

                order.filled += fillable
                counter_order.filled += fillable

                counter_order.status = "EXECUTED" if counter_order.filled == counter_order.original_qty else "PARTIALLY_EXECUTED"
                counter_order.save()
                total_filled += fillable

            except ValidationError as e:
                logger.warning(f"Skipping trade due to: {str(e)}")
                continue

        order.status = (
            "EXECUTED" if order.filled == order.original_qty
            else "PARTIALLY_EXECUTED" if order.filled > 0 else "NEW"
        )
        order.save()

        logger.info(f"Matching finished for order {order.id}: filled={order.filled}, status={order.status}")
        return total_filled

class OrderCreateView(APIView):
    permission_classes = [HasAPIKey]

    def post(self, request):
        is_market = 'price' not in request.data
        serializer_class = MarketOrderCreateSerializer if is_market else LimitOrderCreateSerializer
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                order = serializer.save(user=request.user)

                if isinstance(order, LimitOrder):
                    if order.direction == "BUY":
                        cost = order.price * order.original_qty
                        balance = Balance.objects.select_for_update().get(user=order.user, ticker="RUB")
                        if balance.amount < cost:
                            raise ValidationError("Недостаточно средств")
                        balance.amount -= cost
                        balance.save()
                    else:
                        asset = Balance.objects.select_for_update().get(user=order.user, ticker=order.ticker)
                        if asset.amount < order.original_qty:
                            raise ValidationError("Недостаточно монет")
                        asset.amount -= order.original_qty
                        asset.save()

                filled = OrderMatchingEngine.match_order(order)
                return Response({"order_id": str(order.id), "filled": filled, "status": order.status}, status=201)

        except ValidationError as e:
            return Response({"error": str(e)}, status=400)

class OrderCancelView(APIView):
    permission_classes = [HasAPIKey]

    def delete(self, request, order_id):
        try:
            UUID(order_id)
        except ValueError:
            return Response({"error": "Invalid UUID"}, status=400)

        order = get_object_or_404(LimitOrder, id=order_id, user=request.user)
        if order.status != "NEW":
            return Response({"error": "Only NEW orders can be cancelled"}, status=400)

        try:
            with transaction.atomic():
                remaining = order.original_qty - order.filled
                if order.direction == "BUY":
                    refund = order.price * remaining
                    Balance.objects.filter(user=order.user, ticker="RUB").update(amount=F('amount') + refund)
                else:
                    Balance.objects.filter(user=order.user, ticker=order.ticker).update(amount=F('amount') + remaining)

                order.status = "CANCELLED"
                order.save()
                logger.info(f"Order {order.id} cancelled")
                return Response({"success": True})
        except Exception as e:
            logger.error(f"Cancel error: {e}")
            return Response({"error": "Server error"}, status=500)

class OrderBookView(APIView):
    def get(self, request, ticker):
        limit = min(int(request.query_params.get("limit", 10)), 25)
        orders = LimitOrder.objects.filter(ticker=ticker, status="NEW").annotate(
            remaining_qty=ExpressionWrapper(F("original_qty") - F("filled"), output_field=IntegerField())
        ).filter(remaining_qty__gt=0)

        bids = orders.filter(direction="BUY").values("price").annotate(qty=Sum("remaining_qty")).order_by("-price")[:limit]
        asks = orders.filter(direction="SELL").values("price").annotate(qty=Sum("remaining_qty")).order_by("price")[:limit]

        serializer = OrderbookSerializer({"bids": bids, "asks": asks})
        return Response(serializer.data)

class TransactionHistoryView(APIView):
    def get(self, request, ticker):
        limit = min(int(request.query_params.get("limit", 10)), 100)
        transactions = Transaction.objects.filter(ticker=ticker).order_by("-timestamp")[:limit]
        data = [{"ticker": t.ticker, "amount": t.amount, "price": t.price, "timestamp": t.timestamp.isoformat()} for t in transactions]
        return Response(data)

class InstrumentListView(APIView):
    def get(self, request):
        instruments = Instrument.objects.all()
        data = [{"ticker": i.ticker, "name": i.name} for i in instruments]
        return Response(data)

class BalanceView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request):
        user = get_user_from_token(request)
        balances = Balance.objects.filter(user=user)
        result = {
            balance.ticker: {
                "amount": balance.amount,
                "blocked": balance.blocked
            } for balance in balances
        }
        return Response(result)

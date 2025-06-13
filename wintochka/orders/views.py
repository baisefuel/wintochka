from uuid import UUID
from django.db import transaction
from django.db.models import Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import logging

from .models import MarketOrder, LimitOrder, OrderStatus, Transaction
from .serializers import MarketOrderSerializer, LimitOrderSerializer, CreateOrderResponseSerializer
from users.permissions import HasAPIKey
from users.utils import get_user_from_token
from balances.models import Balance
from instruments.models import Instrument

logger = logging.getLogger(__name__)


def match_order(new_order):
    direction = new_order.direction
    ticker = new_order.ticker
    is_buy = direction == "BUY"

    logger.info(f"[match_order] Matching order: {new_order.id} direction={direction} price={getattr(new_order, 'price', '?')}")

    counter_orders = LimitOrder.objects.filter(
        ticker=ticker,
        direction="SELL" if is_buy else "BUY",
        status="NEW"
    ).exclude(user=new_order.user).order_by("price" if is_buy else "-price", "timestamp")

    qty_remaining = new_order.qty
    total_filled = 0

    for order in counter_orders:
        if (is_buy and new_order.price < order.price) or (not is_buy and new_order.price > order.price):
            break

        trade_qty = min(qty_remaining, order.qty)
        trade_price = order.price

        buyer = new_order.user if is_buy else order.user
        seller = order.user if is_buy else new_order.user

        rub_balance, _ = Balance.objects.get_or_create(user=buyer, ticker="RUB")
        rub_cost = trade_qty * trade_price
        if rub_balance.amount < rub_cost:
            logger.info(f"[match_order] Buyer {buyer.id} has insufficient RUB: {rub_balance.amount} < {rub_cost}")
            continue

        seller_asset, _ = Balance.objects.get_or_create(user=seller, ticker=ticker)
        if seller_asset.amount < trade_qty:
            logger.info(f"[match_order] Seller {seller.id} has insufficient asset: {seller_asset.amount} < {trade_qty}")
            continue

        logger.info(f"[match_order] Executing trade: buyer={buyer.id} seller={seller.id} qty={trade_qty} price={trade_price}")

        rub_balance.amount -= rub_cost
        rub_balance.save()

        seller_rub, _ = Balance.objects.get_or_create(user=seller, ticker="RUB")
        seller_rub.amount += rub_cost
        seller_rub.save()

        buyer_asset, _ = Balance.objects.get_or_create(user=buyer, ticker=ticker)
        buyer_asset.amount += trade_qty
        buyer_asset.save()

        seller_asset.amount -= trade_qty
        seller_asset.save()

        order.qty -= trade_qty
        order.filled += trade_qty
        if order.qty == 0:
            order.status = "EXECUTED"
        else:
            order.status = "PARTIALLY_EXECUTED"
        order.save()

        Transaction.objects.create(ticker=ticker, amount=trade_qty, price=trade_price)

        qty_remaining -= trade_qty
        total_filled += trade_qty

        if qty_remaining == 0:
            break

    new_order.filled += total_filled
    new_order.qty = qty_remaining
    if total_filled == 0:
        new_order.status = "NEW"
    elif qty_remaining == 0:
        new_order.status = "EXECUTED"
    else:
        new_order.status = "PARTIALLY_EXECUTED"
    new_order.save()

class OrderCreateView(APIView):
    permission_classes = [HasAPIKey]

    def post(self, request):
        user = get_user_from_token(request)
        data = request.data
        logger.info(f"[OrderCreateView] New order request by user={user.id} data={data}")

        try:
            is_market = 'price' not in data
            serializer_class = MarketOrderSerializer if is_market else LimitOrderSerializer
            serializer = serializer_class(data=data)

            if not serializer.is_valid():
                logger.warning(f"[OrderCreateView] Validation error: {serializer.errors}")
                return Response(serializer.errors, status=422)

            validated = serializer.validated_data
            ticker = validated.get("ticker")
            direction = validated["direction"]
            qty = validated["qty"]
            price = validated.get("price", 1)

            with transaction.atomic():
                if is_market:
                    limit_orders = LimitOrder.objects.filter(
                        ticker=ticker,
                        direction="SELL" if direction == "BUY" else "BUY",
                        status="NEW"
                    ).order_by("price" if direction == "BUY" else "-price", "timestamp")

                    if not limit_orders.exists():
                        logger.info("[OrderCreateView] No counter orders found for market order")
                        return Response({"error": "Нет встречных заявок для исполнения"}, status=400)

                    best_price = limit_orders.first().price
                    cost = best_price * qty

                    if direction == "BUY":
                        rub_balance = Balance.objects.filter(user=user, ticker="RUB").first()
                        if not rub_balance or rub_balance.amount < cost:
                            return Response({"error": "Недостаточно средств"}, status=400)
                    else:
                        asset_balance = Balance.objects.filter(user=user, ticker=ticker).first()
                        if not asset_balance or asset_balance.amount < qty:
                            return Response({"error": "Недостаточно монет"}, status=400)

                    order = MarketOrder.objects.create(
                        user=user,
                        ticker=ticker,
                        direction=direction,
                        qty=qty,
                        status=OrderStatus.EXECUTED
                    )

                    Transaction.objects.create(ticker=ticker, amount=qty, price=best_price)
                    logger.info(f"[OrderCreateView] Market order created: {order.id}")

                    response_data = {
                        "id": str(order.id),
                        "user_id": str(order.user.id),
                        "direction": order.direction,
                        "ticker": order.ticker,
                        "qty": order.qty,
                        "status": order.status,
                        "timestamp": order.timestamp.isoformat(),
                        "body": {} 
                    }

                else:
                    order = LimitOrder.objects.create(
                        user=user,
                        **validated,
                        original_qty=qty,
                        filled=0
                    )
                    match_order(order)

                    logger.info(f"[OrderCreateView] Limit order created: {order.id}")

                    response_data = {
                        "id": str(order.id),
                        "user_id": str(order.user.id),
                        "direction": order.direction,
                        "ticker": order.ticker,
                        "qty": order.qty,
                        "status": order.status,
                        "timestamp": order.timestamp.isoformat(),
                        "body": {
                            "price": order.price,
                            "filled": order.filled
                        }
                    }

            return Response(response_data, status=200)

        except Exception as e:
            logger.exception(f"[OrderCreateView] Internal error: {e}")
            return Response({"error": "Internal server error"}, status=500)

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
        logger.info(f"[OrderListView] Returned {len(all_orders)} orders for user {user.id}")
        return Response(all_orders)

class OrderDetailCancelView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request, order_id):
        user = get_user_from_token(request)

        try:
            UUID(str(order_id))
        except ValueError:
            logger.warning(f"[OrderDetailCancelView][GET] Invalid UUID: {order_id}")
            return Response({"error": "Invalid UUID"}, status=400)

        order = (
            MarketOrder.objects.filter(id=order_id, user=user).first() or
            LimitOrder.objects.filter(id=order_id, user=user).first()
        )

        if not order:
            logger.info(f"[OrderDetailCancelView][GET] Order not found: {order_id}")
            return Response({"error": "Order not found"}, status=404)

        data = {
            "order_id": str(order.id),
            "user_id": str(order.user.id),
            "direction": order.direction,
            "ticker": order.ticker,
            "qty": order.qty,
            "status": order.status,
            "timestamp": order.timestamp.isoformat(),
        }

        if isinstance(order, LimitOrder):
            data["price"] = order.price
            data["filled"] = order.filled
            data["body"] = "LimitOrder"

        elif isinstance(order, MarketOrder):
            data["body"] = "MarketOrder"

        logger.info(f"[OrderDetailCancelView][GET] Order data returned: {data}")
        return Response(data)

    def delete(self, request, order_id):
        user = get_user_from_token(request)

        try:
            UUID(str(order_id))
        except ValueError:
            logger.warning(f"[OrderDetailCancelView][DELETE] Invalid UUID: {order_id}")
            return Response({"error": "Invalid UUID"}, status=400)

        order = LimitOrder.objects.filter(id=order_id, user=user).first()

        if not order or order.status != "NEW":
            logger.info(f"[OrderDetailCancelView][DELETE] Cannot cancel order {order_id}: not found or not NEW")
            return Response({"error": "Only NEW limit orders can be cancelled or order not found"}, status=400)

        order.status = "CANCELLED"
        order.save()

        logger.info(f"[OrderDetailCancelView][DELETE] Order cancelled: {order_id}")
        return Response({
            "success": True,
            "order_id": str(order.id),
            "user_id": str(user.id)
        })

class OrderBookView(APIView):
    def get(self, request, ticker):
        limit = int(request.query_params.get("limit", 10))
        limit = min(limit, 25)

        orders = LimitOrder.objects.filter(ticker=ticker, status="NEW", qty__gt=0)
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


class InstrumentListView(APIView):
    def get(self, request):
        instruments = Instrument.objects.all()
        return Response([
            {"ticker": i.ticker, "name": i.name}
            for i in instruments
        ])

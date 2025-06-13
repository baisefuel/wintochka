from uuid import UUID
from django.db import transaction
from django.db.models import Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import logging

from .models import MarketOrder, LimitOrder, OrderStatus, Transaction
from .serializers import MarketOrderSerializer, LimitOrderSerializer
from users.permissions import HasAPIKey
from users.utils import get_user_from_token
from balances.models import Balance
from instruments.models import Instrument

logger = logging.getLogger(__name__)

def match_order(new_order):
    logger.info(f"[match_order] Start matching for order {new_order.id}")
    direction = new_order.direction
    ticker = new_order.ticker
    is_buy = direction == "BUY"

    counter_orders_queryset = LimitOrder.objects.filter(
        ticker=ticker,
        direction="SELL" if is_buy else "BUY",
        status="NEW"
    ).exclude(user=new_order.user)

    if is_buy:
        counter_orders = list(counter_orders_queryset.order_by('price', 'timestamp'))
    else:
        counter_orders = list(counter_orders_queryset.order_by('-price', 'timestamp'))

    logger.debug(f"[match_order] Found {len(counter_orders)} counter orders")

    qty_remaining = new_order.original_qty - new_order.filled
    total_filled = 0

    logged_insufficient_users = set()


    for order in counter_orders:
        counter_remaining = order.original_qty - order.filled
        trade_qty = min(qty_remaining, counter_remaining)
        trade_price = order.price
        trade_cost = trade_qty * trade_price

        buyer = new_order.user if is_buy else order.user
        seller = order.user if is_buy else new_order.user

        buyer_rub = Balance.objects.select_for_update().get_or_create(user=buyer, ticker="RUB")[0]
        seller_asset = Balance.objects.select_for_update().get_or_create(user=seller, ticker=ticker)[0]

        if buyer_rub.blocked < trade_cost:
            if buyer.id not in logged_insufficient_users:
                logger.warning(f"[match_order] Buyer {buyer.id} has insufficient blocked RUB: {buyer_rub.blocked} < {trade_cost}")
                logged_insufficient_users.add(buyer.id)
            continue

        if seller_asset.blocked < trade_qty:
            if seller.id not in logged_insufficient_users:
                logger.warning(f"[match_order] Seller {seller.id} has insufficient blocked {ticker}: {seller_asset.blocked} < {trade_qty}")
                logged_insufficient_users.add(seller.id)
            continue

        logger.info(f"[match_order] Executing trade: buyer={buyer.id}, seller={seller.id}, qty={trade_qty}, price={trade_price}")

        buyer_rub.blocked -= trade_cost
        buyer_rub.save()

        seller_rub = Balance.objects.get_or_create(user=seller, ticker="RUB")[0]
        seller_rub.amount += trade_cost
        seller_rub.save()

        buyer_asset = Balance.objects.get_or_create(user=buyer, ticker=ticker)[0]
        buyer_asset.amount += trade_qty
        buyer_asset.save()

        seller_asset.blocked -= trade_qty
        seller_asset.save()

        order.filled += trade_qty
        order.status = (
            "EXECUTED" if order.filled == order.original_qty
            else "PARTIALLY_EXECUTED"
        )
        order.save()

        Transaction.objects.create(ticker=ticker, amount=trade_qty, price=trade_price)

        logger.info(f"[match_order] Trade complete: counter_order={order.id}, filled={order.filled}, status={order.status}")

        qty_remaining -= trade_qty
        total_filled += trade_qty

        if qty_remaining <= 0:
            break

    new_order.filled += total_filled
    new_order.status = (
        "EXECUTED" if new_order.filled == new_order.original_qty
        else "PARTIALLY_EXECUTED" if total_filled > 0
        else "NEW"
    )
    new_order.save()

    logger.info(f"[match_order] Finished matching order {new_order.id}: filled={new_order.filled}, status={new_order.status}")

class OrderCreateView(APIView):
    permission_classes = [HasAPIKey]

    def post(self, request):
        user = get_user_from_token(request)
        data = request.data
        logger.info(f"[OrderCreateView] User {user.id} submitted order: {data}")

        is_market = "price" not in data
        serializer = MarketOrderSerializer(data=data) if is_market else LimitOrderSerializer(data=data)

        if not serializer.is_valid():
            logger.warning(f"[OrderCreateView] Validation error: {serializer.errors}")
            return Response(serializer.errors, status=422)

        validated = serializer.validated_data
        ticker = validated["ticker"]
        direction = validated["direction"]
        qty = validated["qty"]

        logger.debug(f"[OrderCreateView] Direction: {direction}, Ticker: {ticker}, Qty: {qty}, Market: {is_market}")

        try:
            with transaction.atomic():
                if is_market:
                    logger.info(f"[OrderCreateView] Creating market order for user {user.id}")
                    counter_orders = LimitOrder.objects.filter(
                        ticker=ticker,
                        direction="SELL" if direction == "BUY" else "BUY",
                        status="NEW"
                    ).order_by("price" if direction == "BUY" else "-price", "timestamp")

                    if not counter_orders.exists():
                        logger.warning("[OrderCreateView] No counter orders found")
                        return Response({"error": "Нет встречных заявок"}, status=400)

                    best_price = counter_orders.first().price
                    cost = best_price * qty
                    logger.debug(f"[OrderCreateView] Best price: {best_price}, Cost: {cost}")

                    if direction == "BUY":
                        rub = Balance.objects.get_or_create(user=user, ticker="RUB", defaults={"amount": 0, "blocked": 0})[0]
                        if rub.amount < cost:
                            logger.warning("[OrderCreateView] Insufficient RUB for market BUY")
                            return Response({"error": "Недостаточно средств"}, status=400)
                        rub.amount -= cost
                        rub.save()
                    else:
                        asset = Balance.objects.get_or_create(user=user, ticker=ticker, defaults={"amount": 0, "blocked": 0})[0]
                        if asset.amount < qty:
                            logger.warning("[OrderCreateView] Insufficient asset for market SELL")
                            return Response({"error": "Недостаточно монет"}, status=400)
                        asset.amount -= qty
                        asset.save()

                    order = MarketOrder.objects.create(
                        user=user,
                        ticker=ticker,
                        direction=direction,
                        qty=qty,
                        status=OrderStatus.EXECUTED
                    )
                    Transaction.objects.create(ticker=ticker, amount=qty, price=best_price)
                    logger.info(f"[OrderCreateView] Market order {order.id} executed")
                    return Response({"success": True, "order_id": str(order.id)})

                else:
                    logger.info(f"[OrderCreateView] Creating limit order for user {user.id}")
                    price = validated["price"]
                    cost = price * qty

                    if direction == "BUY":
                        rub = Balance.objects.get_or_create(user=user, ticker="RUB", defaults={"amount": 0, "blocked": 0})[0]
                        if rub.amount < cost:
                            logger.warning("[OrderCreateView] Insufficient RUB for limit BUY")
                            return Response({"error": "Недостаточно средств"}, status=400)
                        rub.amount -= cost
                        rub.blocked += cost
                        rub.save()
                    else:
                        asset = Balance.objects.get_or_create(user=user, ticker=ticker, defaults={"amount": 0, "blocked": 0})[0]
                        if asset.amount < qty:
                            logger.warning("[OrderCreateView] Insufficient asset for limit SELL")
                            return Response({"error": "Недостаточно монет"}, status=400)
                        asset.amount -= qty
                        asset.blocked += qty
                        asset.save()

                    order = LimitOrder.objects.create(
                        user=user,
                        ticker=ticker,
                        direction=direction,
                        price=price,
                        original_qty=qty,
                        filled=0,
                        status=OrderStatus.NEW
                    )
                    logger.info(f"[OrderCreateView] Limit order {order.id} created, starting match")
                    match_order(order)
                    return Response({"success": True, "order_id": str(order.id)})

        except Exception as e:
            logger.exception(f"[OrderCreateView] Internal error: {e}")
            return Response({"error": "Internal server error"}, status=500)


class OrderListView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request):
        user = get_user_from_token(request)
        logger.info(f"[OrderListView] User {user.id} requested order list")

        market_orders = MarketOrder.objects.filter(user=user)
        limit_orders = LimitOrder.objects.filter(user=user)

        def serialize(order):
            data = {
                "id": str(order.id),
                "status": order.status,
                "user_id": str(order.user.id),
                "timestamp": order.timestamp.isoformat(),
            }
            if isinstance(order, MarketOrder):
                data["body"] = {
                    "direction": order.direction,
                    "ticker": order.ticker,
                    "qty": order.qty
                }
            else:
                data["body"] = {
                    "direction": order.direction,
                    "ticker": order.ticker,
                    "qty": order.original_qty,
                    "price": order.price
                }
                data["filled"] = order.filled
                data["remaining"] = order.original_qty - order.filled
            return data

        result = list(map(serialize, market_orders)) + list(map(serialize, limit_orders))
        logger.info(f"[OrderListView] Returned {len(result)} orders")
        return Response(result)


class OrderDetailCancelView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request, order_id):
        user = get_user_from_token(request)
        logger.info(f"[OrderDetailView] User {user.id} requested details for order {order_id}")

        try:
            UUID(str(order_id))
        except ValueError:
            logger.warning("[OrderDetailView] Invalid UUID")
            return Response({"error": "Invalid UUID"}, status=status.HTTP_400_BAD_REQUEST)

        order = LimitOrder.objects.filter(id=order_id, user=user).first()
        if not order:
            order = MarketOrder.objects.filter(id=order_id, user=user).first()

        if not order:
            logger.warning(f"[OrderDetailView] Order {order_id} not found for user {user.id}")
            return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

        def serialize_order_detail(order):
            data = {
                "id": str(order.id),
                "status": order.status,
                "user_id": str(order.user.id),
                "timestamp": order.timestamp.isoformat(),
                "body": {
                    "direction": order.direction,
                    "ticker": order.ticker,
                    "qty": order.qty if isinstance(order, MarketOrder) else order.original_qty
                }
            }
            if isinstance(order, LimitOrder):
                data["body"]["price"] = order.price
                data["filled"] = order.filled
                data["remaining"] = order.original_qty - order.filled
            return data

        serialized_data = serialize_order_detail(order)
        logger.info(f"[OrderDetailView] Returned details for order {order_id}")
        return Response(serialized_data, status=status.HTTP_200_OK)

    def delete(self, request, order_id):
        user = get_user_from_token(request)
        logger.info(f"[OrderDetailCancelView] User {user.id} requests cancel for {order_id}")

        try:
            UUID(str(order_id))
        except ValueError:
            logger.warning("[OrderDetailCancelView] Invalid UUID")
            return Response({"error": "Invalid UUID"}, status=400)

        order = LimitOrder.objects.filter(id=order_id, user=user).first()
        if not order:
            logger.warning("[OrderDetailCancelView] Order not found")
            return Response({"error": "Order not found"}, status=404)

        if order.status != OrderStatus.NEW:
            logger.warning(f"[OrderDetailCancelView] Cannot cancel order {order.id}, status is {order.status}")
            return Response({"error": "Only NEW limit orders can be cancelled"}, status=400)

        remaining = order.original_qty - order.filled
        if order.direction == "BUY":
            refund = order.price * remaining
            rub = Balance.objects.get(user=user, ticker="RUB", defaults={"amount": 0, "blocked": 0})
            rub.amount += refund
            rub.blocked -= refund
            rub.save()
            logger.info(f"[OrderDetailCancelView] Refunded RUB: {refund} to user {user.id}")
        else:
            asset = Balance.objects.get(user=user, ticker=order.ticker, defaults={"amount": 0, "blocked": 0})
            asset.amount += remaining
            asset.blocked -= remaining
            asset.save()
            logger.info(f"[OrderDetailCancelView] Refunded {remaining} {order.ticker} to user {user.id}")

        order.status = OrderStatus.CANCELLED
        order.save()
        logger.info(f"[OrderDetailCancelView] Order {order.id} cancelled")
        return Response({"success": True})

class OrderBookView(APIView):
    def get(self, request, ticker):
        limit = min(int(request.query_params.get("limit", 10)), 25)
        logger.info(f"[OrderBookView] Getting orderbook for {ticker} with limit {limit}")

        orders = LimitOrder.objects.filter(ticker=ticker, status="NEW", original_qty__gt=0)

        bids = orders.filter(direction="BUY").values("price").annotate(qty=Sum("original_qty")).order_by("-price")[:limit]

        asks = orders.filter(direction="SELL").values("price").annotate(qty=Sum("original_qty")).order_by("price")[:limit]

        logger.info("[OrderBookView] Orderbook fetched")
        return Response({"bid_levels": list(bids), "ask_levels": list(asks)})

class TransactionHistoryView(APIView):
    def get(self, request, ticker):
        limit = min(int(request.query_params.get("limit", 10)), 100)
        logger.info(f"[TransactionHistoryView] Getting transaction history for {ticker} with limit {limit}")
        transactions = Transaction.objects.filter(ticker=ticker).order_by("-timestamp")[:limit]

        response = [
            {
                "ticker": t.ticker,
                "amount": t.amount,
                "price": t.price,
                "timestamp": t.timestamp.isoformat()
            } for t in transactions
        ]
        logger.info("[TransactionHistoryView] Transactions returned")
        return Response(response)


class InstrumentListView(APIView):
    def get(self, request):
        logger.info("[InstrumentListView] Listing all instruments")
        instruments = Instrument.objects.all()
        response = [{"ticker": i.ticker, "name": i.name} for i in instruments]
        logger.info(f"[InstrumentListView] Returned {len(response)} instruments")
        return Response(response)

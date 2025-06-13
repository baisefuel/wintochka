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

    counter_orders = LimitOrder.objects.filter(
        ticker=ticker,
        direction="SELL" if is_buy else "BUY",
        status="NEW"
    ).exclude(user=new_order.user).order_by(
        "price" if is_buy else "-price",
        "timestamp"
    )

    qty_remaining = new_order.qty
    total_filled = 0

    for order in counter_orders:
        logger.info(f"[match_order] Evaluating counter order {order.id} with price {order.price} and qty {order.qty}")

        if (is_buy and new_order.price < order.price) or (not is_buy and new_order.price > order.price):
            logger.info("[match_order] Price mismatch, stopping match loop")
            break

        buyer = new_order.user if is_buy else order.user
        seller = order.user if is_buy else new_order.user

        buyer_rub, _ = Balance.objects.get_or_create(user=buyer, ticker="RUB")
        seller_asset, _ = Balance.objects.get_or_create(user=seller, ticker=ticker)

        trade_qty = min(qty_remaining, order.qty)
        trade_price = order.price
        total_cost = trade_qty * trade_price

        if buyer_rub.amount < total_cost:
            logger.info(f"[match_order] Buyer {buyer.id} has insufficient funds: {buyer_rub.amount} < {total_cost}")
            continue

        if seller_asset.amount < trade_qty:
            logger.info(f"[match_order] Seller {seller.id} has insufficient asset: {seller_asset.amount} < {trade_qty}")
            continue

        logger.info(f"[match_order] Executing trade: buyer={buyer.id}, seller={seller.id}, qty={trade_qty}, price={trade_price}")

        buyer_rub.amount -= total_cost
        buyer_rub.save()

        seller_rub, _ = Balance.objects.get_or_create(user=seller, ticker="RUB")
        seller_rub.amount += total_cost
        seller_rub.save()

        buyer_asset, _ = Balance.objects.get_or_create(user=buyer, ticker=ticker)
        buyer_asset.amount += trade_qty
        buyer_asset.save()

        seller_asset.amount -= trade_qty
        seller_asset.save()

        order.qty -= trade_qty
        order.filled += trade_qty
        order.status = "EXECUTED" if order.qty == 0 else "PARTIALLY_EXECUTED"
        order.save()

        Transaction.objects.create(ticker=ticker, amount=trade_qty, price=trade_price)

        logger.info(f"[match_order] Trade executed and order {order.id} updated. Remaining qty: {order.qty}")

        qty_remaining -= trade_qty
        total_filled += trade_qty

        if qty_remaining <= 0:
            break

    new_order.filled += total_filled
    new_order.status = (
        "NEW" if total_filled == 0 else
        "EXECUTED" if qty_remaining == 0 else
        "PARTIALLY_EXECUTED"
    )
    new_order.save()
    logger.info(f"[match_order] Matching finished for order {new_order.id}. Final status: {new_order.status}")


class OrderCreateView(APIView):
    permission_classes = [HasAPIKey]

    def post(self, request):
        user = get_user_from_token(request)
        data = request.data
        logger.info(f"[OrderCreateView] Received order from user {user.id}: {data}")

        is_market = 'price' not in data
        serializer = MarketOrderSerializer(data=data) if is_market else LimitOrderSerializer(data=data)

        if not serializer.is_valid():
            logger.warning(f"[OrderCreateView] Validation failed: {serializer.errors}")
            return Response(serializer.errors, status=422)

        validated = serializer.validated_data
        ticker = validated["ticker"]
        direction = validated["direction"]
        qty = validated["qty"]

        try:
            with transaction.atomic():
                if is_market:
                    logger.info("[OrderCreateView] Creating market order")
                    limit_orders = LimitOrder.objects.filter(
                        ticker=ticker,
                        direction="SELL" if direction == "BUY" else "BUY",
                        status="NEW"
                    ).order_by("price" if direction == "BUY" else "-price", "timestamp")

                    if not limit_orders.exists():
                        logger.info("[OrderCreateView] No counter orders available")
                        return Response({"error": "Нет встречных заявок для исполнения"}, status=400)

                    best_price = limit_orders.first().price
                    cost = best_price * qty

                    if direction == "BUY":
                        rub_balance = Balance.objects.filter(user=user, ticker="RUB").first()
                        if not rub_balance or rub_balance.amount < cost:
                            logger.info("[OrderCreateView] Insufficient RUB balance")
                            return Response({"error": "Недостаточно средств"}, status=400)
                    else:
                        asset_balance = Balance.objects.filter(user=user, ticker=ticker).first()
                        if not asset_balance or asset_balance.amount < qty:
                            logger.info("[OrderCreateView] Insufficient asset balance")
                            return Response({"error": "Недостаточно монет"}, status=400)

                    order = MarketOrder.objects.create(
                        user=user,
                        ticker=ticker,
                        direction=direction,
                        qty=qty,
                        status=OrderStatus.EXECUTED
                    )

                    Transaction.objects.create(ticker=ticker, amount=qty, price=best_price)
                    logger.info(f"[OrderCreateView] Market order {order.id} created")

                    return Response({"success": True, "order_id": str(order.id)}, status=200)

                else:
                    logger.info("[OrderCreateView] Creating limit order")
                    order = LimitOrder.objects.create(
                        user=user,
                        **validated,
                        original_qty=qty,
                        filled=0
                    )
                    match_order(order)

                    logger.info(f"[OrderCreateView] Limit order {order.id} created with status {order.status}")
                    return Response({"success": True, "order_id": str(order.id)}, status=200)

        except Exception as e:
            logger.exception(f"[OrderCreateView] Internal error: {e}")
            return Response({"error": "Internal server error"}, status=500)


class OrderListView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request):
        user = get_user_from_token(request)
        logger.info(f"[OrderListView] Listing orders for user {user.id}")
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
            elif isinstance(order, LimitOrder):
                data["body"] = {
                    "direction": order.direction,
                    "ticker": order.ticker,
                    "qty": order.qty,
                    "price": order.price
                }
                data["filled"] = order.filled
            return data

        response = list(map(serialize, market_orders)) + list(map(serialize, limit_orders))
        logger.info(f"[OrderListView] Returned {len(response)} orders")
        return Response(response)


class OrderDetailCancelView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request, order_id):
        user = get_user_from_token(request)
        logger.info(f"[OrderDetailCancelView] Fetching order {order_id} for user {user.id}")
        try:
            UUID(str(order_id))
        except ValueError:
            logger.warning("[OrderDetailCancelView] Invalid UUID")
            return Response({"error": "Invalid UUID"}, status=400)

        order = MarketOrder.objects.filter(id=order_id, user=user).first() or \
                LimitOrder.objects.filter(id=order_id, user=user).first()

        if not order:
            logger.info("[OrderDetailCancelView] Order not found")
            return Response({"error": "Order not found"}, status=404)

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
        elif isinstance(order, LimitOrder):
            data["body"] = {
                "direction": order.direction,
                "ticker": order.ticker,
                "qty": order.qty,
                "price": order.price
            }
            data["filled"] = order.filled

        logger.info(f"[OrderDetailCancelView] Order data: {data}")
        return Response(data)

    def delete(self, request, order_id):
        user = get_user_from_token(request)
        logger.info(f"[OrderDetailCancelView] Cancel request for order {order_id}")
        try:
            UUID(str(order_id))
        except ValueError:
            logger.warning("[OrderDetailCancelView] Invalid UUID")
            return Response({"error": "Invalid UUID"}, status=400)

        order = LimitOrder.objects.filter(id=order_id, user=user).first()

        if not order or order.status != "NEW":
            logger.info("[OrderDetailCancelView] Cannot cancel: not found or status is not NEW")
            return Response({"error": "Only NEW limit orders can be cancelled or order not found"}, status=400)

        order.status = "CANCELLED"
        order.save()
        logger.info(f"[OrderDetailCancelView] Order {order_id} cancelled")
        return Response({"success": True})


class OrderBookView(APIView):
    def get(self, request, ticker):
        limit = min(int(request.query_params.get("limit", 10)), 25)
        logger.info(f"[OrderBookView] Getting orderbook for {ticker} with limit {limit}")

        orders = LimitOrder.objects.filter(ticker=ticker, status="NEW", qty__gt=0)
        bids = orders.filter(direction="BUY").values("price").annotate(qty=Sum("qty")).order_by("-price")[:limit]
        asks = orders.filter(direction="SELL").values("price").annotate(qty=Sum("qty")).order_by("price")[:limit]

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

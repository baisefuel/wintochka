from django.urls import path
from .views import (
    OrderCreateView,
    OrderCancelView,
    OrderBookView,
    TransactionHistoryView,
    InstrumentListView,
    BalanceView,
)

urlpatterns = [
    path("api/v1/order", OrderCreateView.as_view(), name="create-order"),
    path("api/v1/order/<uuid:order_id>", OrderCancelView.as_view(), name="cancel-order"),
    path("api/v1/orderbook/<str:ticker>", OrderBookView.as_view(), name="orderbook"),
    path("api/v1/transactions/<str:ticker>", TransactionHistoryView.as_view(), name="transactions"),
    path("api/v1/instruments", InstrumentListView.as_view(), name="instrument-list"),
    path("api/v1/balance", BalanceView.as_view(), name="user-balance"),
]

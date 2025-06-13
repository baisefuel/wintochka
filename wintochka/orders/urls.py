from django.urls import path
from .views import (
    OrderBookView,
    OrderCreateView,
    OrderDetailCancelView,
    OrderListView,
    TransactionHistoryView,
    InstrumentListView,
)

urlpatterns = [
    path("api/v1/order", OrderCreateView.as_view()),
    path("api/v1/order/<uuid:order_id>", OrderDetailCancelView.as_view()),
    path("api/v1/public/orderbook/<str:ticker>", OrderBookView.as_view()),
    path("api/v1/public/transactions/<str:ticker>", TransactionHistoryView.as_view()),
    path("api/v1/order/list", OrderListView.as_view()),
    path("api/v1/public/instrument", InstrumentListView.as_view()),
]

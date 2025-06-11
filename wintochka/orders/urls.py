from django.urls import path
from .views import (
    OrderBookView,
    OrderCreateView,
    OrderDetailCancelView,
    OrderListView,
    TransactionHistoryView,
)

urlpatterns = [
    path("api/v1/order", OrderCreateView.as_view()),
    path("api/v1/order", OrderListView.as_view()),
    path("api/v1/order/<uuid:order_id>", OrderDetailCancelView.as_view()),
    path("api/v1/public/orderbook/<str:ticker>", OrderBookView.as_view()),
    path("api/v1/public/transactions/<str:ticker>", TransactionHistoryView.as_view()),    
]
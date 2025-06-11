from django.urls import path
from .views import BalanceView

urlpatterns = [
    path("api/v1/balance", BalanceView.as_view()),
]

from django.urls import path
from .views import AdminAddInstrumentView, AdminBalanceDepositView, AdminBalanceWithdrawView, AdminDeleteInstrumentView, AdminDeleteUserView

urlpatterns = [
    path("api/v1/admin/user/<uuid:user_id>", AdminDeleteUserView.as_view()),
    path("api/v1/admin/balance/deposit", AdminBalanceDepositView.as_view()),
    path("api/v1/admin/balance/withdraw", AdminBalanceWithdrawView.as_view()),
    path("api/v1/admin/instrument", AdminAddInstrumentView.as_view()),
    path("api/v1/admin/instrument/<str:ticker>", AdminDeleteInstrumentView.as_view()),
]

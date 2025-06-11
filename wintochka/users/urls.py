from django.urls import path
from .views import RegisterView

urlpatterns = [
    path("api/v1/public/register", RegisterView.as_view(), name="register"),
]

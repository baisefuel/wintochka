from rest_framework.views import APIView
from rest_framework.response import Response
from users.permissions import HasAPIKey
from users.utils import get_user_from_token
from .models import Balance

class BalanceView(APIView):
    permission_classes = [HasAPIKey]
    def get(self, request):
        user = get_user_from_token(request)
        balances = Balance.objects.filter(user=user)
        data = {b.ticker: b.amount for b in balances}
        return Response(data)

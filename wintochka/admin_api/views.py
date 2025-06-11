from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from uuid import UUID
from users.models import User
from users.permissions import IsAdminAPIKey
from django.shortcuts import get_object_or_404

from balances.models import Balance
from instruments.models import Instrument

class AdminDeleteUserView(APIView):
    permission_classes = [IsAdminAPIKey]

    def delete(self, request, user_id):
        try:
            uuid_val = UUID(user_id)
        except ValueError:
            return Response({"error": "Invalid UUID"}, status=400)

        user = get_object_or_404(User, id=user_id)
        data = {
            "id": str(user.id),
            "name": user.name,
            "role": user.role,
            "api_key": str(user.api_key)
        }
        user.delete()
        return Response(data)

class AdminBalanceDepositView(APIView):
    permission_classes = [IsAdminAPIKey]

    def post(self, request):
        data = request.data
        required_fields = {"user_id", "ticker", "amount"}
        if not required_fields.issubset(data):
            return Response({"error": "Missing required fields"}, status=400)

        try:
            uuid_val = UUID(data["user_id"])
            amount = int(data["amount"])
            if amount <= 0:
                raise ValueError()
        except ValueError:
            return Response({"error": "Invalid user_id or amount"}, status=400)

        try:
            user = User.objects.get(id=data["user_id"])
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        balance, _ = Balance.objects.get_or_create(user=user, ticker=data["ticker"])
        balance.amount += amount
        balance.save()

        return Response({"success": True})
    
class AdminBalanceWithdrawView(APIView):
    permission_classes = [IsAdminAPIKey]

    def post(self, request):
        data = request.data
        required_fields = {"user_id", "ticker", "amount"}
        if not required_fields.issubset(data):
            return Response({"error": "Missing required fields"}, status=400)

        try:
            UUID(data["user_id"])
            amount = int(data["amount"])
            if amount <= 0:
                raise ValueError()
        except ValueError:
            return Response({"error": "Invalid user_id or amount"}, status=400)

        try:
            user = User.objects.get(id=data["user_id"])
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        try:
            balance = Balance.objects.get(user=user, ticker=data["ticker"])
        except Balance.DoesNotExist:
            return Response({"error": "Balance not found"}, status=404)

        if balance.amount < amount:
            return Response({"error": "Insufficient funds"}, status=400)

        balance.amount -= amount
        balance.save()

        return Response({"success": True})

class AdminAddInstrumentView(APIView):
    permission_classes = [IsAdminAPIKey]

    def post(self, request):
        data = request.data
        name = data.get("name")
        ticker = data.get("ticker")

        if not name or not ticker:
            return Response({"error": "Missing name or ticker"}, status=400)

        if not ticker.isupper() or not (2 <= len(ticker) <= 10):
            return Response({"error": "Invalid ticker format"}, status=400)

        if Instrument.objects.filter(ticker=ticker).exists():
            return Response({"error": "Instrument already exists"}, status=400)

        Instrument.objects.create(name=name, ticker=ticker)
        return Response({"success": True})
    
class AdminDeleteInstrumentView(APIView):
    permission_classes = [IsAdminAPIKey]

    def delete(self, request, ticker):
        try:
            instrument = Instrument.objects.get(ticker=ticker)
        except Instrument.DoesNotExist:
            return Response({"error": "Instrument not found"}, status=404)

        instrument.delete()
        return Response({"success": True})
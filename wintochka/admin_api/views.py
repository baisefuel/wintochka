from uuid import UUID
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers
from users.models import User
from users.permissions import IsAdminAPIKey
from django.shortcuts import get_object_or_404
from balances.models import Balance
from instruments.models import Instrument

import logging

logger = logging.getLogger(__name__)


class AdminDeleteUserView(APIView):
    permission_classes = [IsAdminAPIKey]

    def delete(self, request, user_id):
        try:
            user_id = UUID(str(user_id)) 
        except (ValueError, TypeError):
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
            raw_user = data.get("user_id")
            raw_ticker = data.get("ticker")
            raw_amount = data.get("amount")
            UUID(raw_user)
            if not isinstance(raw_ticker, str):
                raise ValueError()
            amount = int(raw_amount)
            if amount <= 0:
                raise ValueError()
            ticker = raw_ticker
        except Exception:
            return Response({"error": "Invalid user_id, ticker, or amount"}, status=400)

        try:
            user = User.objects.get(id=data["user_id"])
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        balance, _ = Balance.objects.get_or_create(user=user, ticker=ticker)
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
            raw_user = data.get("user_id")
            raw_ticker = data.get("ticker")
            raw_amount = data.get("amount")
            UUID(raw_user)
            if not isinstance(raw_ticker, str):
                raise ValueError()
            amount = int(raw_amount)
            if amount <= 0:
                raise ValueError()
            ticker = raw_ticker
        except Exception:
            return Response({"error": "Invalid user_id, ticker, or amount"}, status=400)

        try:
            user = User.objects.get(id=data["user_id"])
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        try:
            balance = Balance.objects.get(user=user, ticker=ticker)
        except Balance.DoesNotExist:
            return Response({"error": "Balance not found"}, status=404)

        if balance.amount < amount:
            return Response({"error": "Insufficient funds"}, status=400)

        balance.amount -= amount
        balance.save()

        return Response({"success": True})

class InstrumentSerializer(serializers.Serializer):
    name = serializers.CharField()
    ticker = serializers.RegexField(regex=r'^[A-Z]{2,10}$')

class AdminInstrumentView(APIView):
    permission_classes = [IsAdminAPIKey]

    def get(self, request):
        instruments = Instrument.objects.all()
        logger.info(f"[AdminInstrumentView][GET] Returned {len(instruments)} instruments")
        return Response([
            {"ticker": i.ticker, "name": i.name}
            for i in instruments
        ])

    def post(self, request):
        logger.info(f"[AdminInstrumentView][POST] Incoming data: {request.data}")

        serializer = InstrumentSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"[AdminInstrumentView][POST] Validation error: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        data = serializer.validated_data
        name = data["name"]
        ticker = data["ticker"]

        if Instrument.objects.filter(ticker=ticker).exists():
            logger.warning(f"[AdminInstrumentView][POST] Instrument already exists: {ticker}")
            return Response({"error": "Instrument already exists"}, status=status.HTTP_400_BAD_REQUEST)

        Instrument.objects.create(name=name, ticker=ticker)
        logger.info(f"[AdminInstrumentView][POST] Instrument created: {ticker} - {name}")
        return Response({"success": True}, status=status.HTTP_200_OK)

class AdminDeleteInstrumentView(APIView):
    permission_classes = [IsAdminAPIKey]

    def delete(self, request, ticker):
        try:
            instrument = Instrument.objects.get(ticker=ticker)
        except Instrument.DoesNotExist:
            return Response({"error": "Instrument not found"}, status=404)

        instrument.delete()
        return Response({"success": True})


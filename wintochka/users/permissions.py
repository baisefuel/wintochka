from rest_framework.permissions import BasePermission
from users.models import User

class HasAPIKey(BasePermission):
    def has_permission(self, request, view):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("TOKEN "):
            return False
        token = auth_header.split("TOKEN ")[1]
        return User.objects.filter(api_key=token).exists()

class IsAdminAPIKey(BasePermission):
    def has_permission(self, request, view):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("TOKEN "):
            return False
        token = auth_header.split("TOKEN ")[1]
        return User.objects.filter(api_key=token, role="ADMIN").exists()

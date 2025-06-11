from users.models import User
from rest_framework.exceptions import AuthenticationFailed

def get_user_from_token(request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("TOKEN "):
        raise AuthenticationFailed("Invalid or missing TOKEN header")

    token = auth_header.split("TOKEN ")[1]
    try:
        return User.objects.get(api_key=token)
    except User.DoesNotExist:
        raise AuthenticationFailed("Invalid API key")

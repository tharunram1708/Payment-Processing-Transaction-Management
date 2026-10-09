from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from transactions.authentication import TokenError, decode_access_token
from transactions.models import RevokedToken


class JWTAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.jwt_auth_error = None
        request.jwt_payload = None
        request.jwt_token = None

        authorization = request.META.get("HTTP_AUTHORIZATION", "")
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            self._authenticate(request, token)

        return self.get_response(request)

    def _authenticate(self, request, token: str) -> None:
        try:
            payload = decode_access_token(token)
            if RevokedToken.objects.filter(jti=payload["jti"]).exists():
                raise TokenError("Token has been revoked.")

            user = get_user_model().objects.get(pk=payload["sub"], is_active=True)
        except (TokenError, get_user_model().DoesNotExist) as exc:
            request.user = AnonymousUser()
            request.jwt_auth_error = str(exc) or "Authentication failed."
            return

        request.user = user
        request.jwt_payload = payload
        request.jwt_token = token

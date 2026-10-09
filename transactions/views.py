import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from transactions.authentication import create_access_token
from transactions.models import RevokedToken, SavedCard, Transaction
from transactions.serializers import serialize_saved_card, serialize_transaction, serialize_user


def home_page(request):
    if request.user.is_authenticated:
        return redirect("card-list-page")
    return redirect("login-page")


@require_http_methods(["GET", "POST"])
def register_page(request):
    if request.user.is_authenticated:
        return redirect("card-list-page")

    if request.method == "GET":
        return render(request, "transactions/register.html")

    user_data, error = _validate_registration_payload(request.POST)
    if error:
        messages.error(request, error)
        return render(request, "transactions/register.html", {"form": request.POST}, status=400)

    user_model = get_user_model()
    if user_model.objects.filter(username=user_data["username"]).exists():
        messages.error(request, "Username already exists.")
        return render(request, "transactions/register.html", {"form": request.POST}, status=409)

    user = user_model.objects.create_user(**user_data)
    auth_login(request, user)
    messages.success(request, "Account created.")
    return redirect("card-list-page")


@require_http_methods(["GET", "POST"])
def login_page(request):
    if request.user.is_authenticated:
        return redirect("card-list-page")

    if request.method == "GET":
        return render(request, "transactions/login.html")

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user = authenticate(request, username=username, password=password)
    if user is None:
        messages.error(request, "Invalid username or password.")
        return render(request, "transactions/login.html", {"form": request.POST}, status=401)

    auth_login(request, user)
    return redirect(request.GET.get("next") or "card-list-page")


@require_POST
def logout_page(request):
    auth_logout(request)
    return redirect("login-page")


@login_required(login_url="login-page")
@require_http_methods(["GET", "POST"])
def card_list_page(request):
    if request.method == "POST":
        card_data, error = _validate_card_payload(request.POST)
        if error:
            messages.error(request, error)
        else:
            SavedCard.objects.create(user=request.user, **card_data)
            messages.success(request, "Card saved.")
            return redirect("card-list-page")

    return render(
        request,
        "transactions/cards.html",
        {
            "cards": SavedCard.objects.filter(user=request.user),
            "current_year": timezone.localdate().year,
        },
    )


@login_required(login_url="login-page")
@require_POST
def delete_card_page(request, card_id):
    deleted_count, _ = SavedCard.objects.filter(id=card_id, user=request.user).delete()
    if deleted_count:
        messages.success(request, "Card deleted.")
    else:
        messages.error(request, "Card not found.")
    return redirect("card-list-page")


@csrf_exempt
@require_POST
def register(request):
    payload, error = _json_payload(request)
    if error:
        return JsonResponse({"detail": error}, status=400)

    user_data, error = _validate_registration_payload(payload)
    if error:
        return JsonResponse({"detail": error}, status=400)

    user_model = get_user_model()
    if user_model.objects.filter(username=user_data["username"]).exists():
        return JsonResponse({"detail": "Username already exists."}, status=409)

    user = user_model.objects.create_user(**user_data)
    token, token_payload = create_access_token(user)

    return JsonResponse(
        {
            "user": serialize_user(user),
            "access_token": token,
            "token_type": "Bearer",
            "expires_at": datetime.fromtimestamp(
                token_payload["exp"],
                tz=timezone.get_current_timezone(),
            ).isoformat(),
        },
        status=201,
    )


@csrf_exempt
@require_POST
def login(request):
    payload, error = _json_payload(request)
    if error:
        return JsonResponse({"detail": error}, status=400)

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        return JsonResponse({"detail": "username and password are required."}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "Invalid username or password."}, status=401)

    token, token_payload = create_access_token(user)
    return JsonResponse(
        {
            "user": serialize_user(user),
            "access_token": token,
            "token_type": "Bearer",
            "expires_at": datetime.fromtimestamp(
                token_payload["exp"],
                tz=timezone.get_current_timezone(),
            ).isoformat(),
        }
    )


@csrf_exempt
@require_POST
def logout(request):
    auth_response = _authentication_required(request)
    if auth_response is not None:
        return auth_response

    expires_at = datetime.fromtimestamp(
        request.jwt_payload["exp"],
        tz=timezone.get_current_timezone(),
    )
    RevokedToken.objects.get_or_create(
        jti=request.jwt_payload["jti"],
        defaults={"user": request.user, "expires_at": expires_at},
    )
    return JsonResponse({"detail": "Logged out successfully."})


@require_GET
def current_user(request):
    auth_response = _authentication_required(request)
    if auth_response is not None:
        return auth_response

    return JsonResponse({"user": serialize_user(request.user)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def saved_cards(request):
    auth_response = _authentication_required(request)
    if auth_response is not None:
        return auth_response

    if request.method == "GET":
        cards = SavedCard.objects.filter(user=request.user)
        return JsonResponse(
            {
                "count": cards.count(),
                "cards": [serialize_saved_card(card) for card in cards],
            }
        )

    payload, error = _json_payload(request)
    if error:
        return JsonResponse({"detail": error}, status=400)

    card_data, error = _validate_card_payload(payload)
    if error:
        return JsonResponse({"detail": error}, status=400)

    card = SavedCard.objects.create(user=request.user, **card_data)
    return JsonResponse({"card": serialize_saved_card(card)}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
def delete_saved_card(request, card_id):
    auth_response = _authentication_required(request)
    if auth_response is not None:
        return auth_response

    deleted_count, _ = SavedCard.objects.filter(id=card_id, user=request.user).delete()
    if deleted_count == 0:
        return JsonResponse({"detail": "Card not found."}, status=404)

    return JsonResponse({"detail": "Card deleted successfully."})


@require_GET
def transaction_history(request):
    auth_response = _authentication_required(request)
    if auth_response is not None:
        return auth_response

    queryset = Transaction.objects.filter(user=request.user)
    queryset, error = _apply_filters(queryset, request.GET)
    if error is not None:
        return JsonResponse({"detail": error}, status=400)

    return JsonResponse(
        {
            "count": queryset.count(),
            "transactions": [serialize_transaction(transaction) for transaction in queryset],
        }
    )


@require_GET
def transaction_details(request, transaction_id):
    auth_response = _authentication_required(request)
    if auth_response is not None:
        return auth_response

    try:
        transaction = Transaction.objects.get(
            transaction_id=transaction_id,
            user=request.user,
        )
    except Transaction.DoesNotExist:
        return JsonResponse({"detail": "Transaction not found."}, status=404)

    return JsonResponse(serialize_transaction(transaction))


def _apply_filters(queryset, query_params):
    date_value = query_params.get("date")
    min_date = query_params.get("date_from")
    max_date = query_params.get("date_to")
    amount = query_params.get("amount")
    min_amount = query_params.get("min_amount")
    max_amount = query_params.get("max_amount")
    payment_status = query_params.get("status") or query_params.get("payment_status")

    if date_value:
        parsed_date = _parse_date(date_value)
        if parsed_date is None:
            return queryset, "date must use YYYY-MM-DD format."
        queryset = queryset.filter(created_at__date=parsed_date)

    if min_date:
        parsed_date = _parse_date(min_date)
        if parsed_date is None:
            return queryset, "date_from must use YYYY-MM-DD format."
        queryset = queryset.filter(created_at__date__gte=parsed_date)

    if max_date:
        parsed_date = _parse_date(max_date)
        if parsed_date is None:
            return queryset, "date_to must use YYYY-MM-DD format."
        queryset = queryset.filter(created_at__date__lte=parsed_date)

    if amount:
        parsed_amount = _parse_decimal(amount)
        if parsed_amount is None:
            return queryset, "amount must be a valid decimal."
        queryset = queryset.filter(amount=parsed_amount)

    if min_amount:
        parsed_amount = _parse_decimal(min_amount)
        if parsed_amount is None:
            return queryset, "min_amount must be a valid decimal."
        queryset = queryset.filter(amount__gte=parsed_amount)

    if max_amount:
        parsed_amount = _parse_decimal(max_amount)
        if parsed_amount is None:
            return queryset, "max_amount must be a valid decimal."
        queryset = queryset.filter(amount__lte=parsed_amount)

    if payment_status:
        normalized_status = payment_status.upper()
        valid_statuses = {choice.value for choice in Transaction.PaymentStatus}
        if normalized_status not in valid_statuses:
            return queryset, "status must be one of PENDING, SUCCESS, or FAILED."
        queryset = queryset.filter(status=normalized_status)

    return queryset, None


def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_decimal(value: str) -> Decimal | None:
    if len(str(value)) > 32:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _json_payload(request) -> tuple[dict, str | None]:
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return {}, "Request body must be valid JSON."

    if not isinstance(payload, dict):
        return {}, "Request body must be a JSON object."
    return payload, None


def _authentication_required(request):
    if request.user.is_authenticated:
        return None

    detail = request.jwt_auth_error or "Authentication required."
    return JsonResponse({"detail": detail}, status=401)


def _validate_registration_payload(payload: dict) -> tuple[dict, str | None]:
    username = str(payload.get("username", "")).strip()
    email = str(payload.get("email", "")).strip()
    password = str(payload.get("password", ""))
    first_name = str(payload.get("first_name", "")).strip()
    last_name = str(payload.get("last_name", "")).strip()

    if not username:
        return {}, "username is required."
    if len(username) > 150:
        return {}, "username must be 150 characters or fewer."
    try:
        UnicodeUsernameValidator()(username)
    except ValidationError:
        return {}, "username contains invalid characters."

    if email:
        if len(email) > 254:
            return {}, "email must be 254 characters or fewer."
        try:
            validate_email(email)
        except ValidationError:
            return {}, "email must be valid."

    if not password:
        return {}, "password is required."
    try:
        validate_password(password)
    except ValidationError as exc:
        return {}, " ".join(exc.messages)

    if len(first_name) > 150:
        return {}, "first_name must be 150 characters or fewer."
    if len(last_name) > 150:
        return {}, "last_name must be 150 characters or fewer."

    return {
        "username": username,
        "email": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
    }, None


def _validate_card_payload(payload: dict) -> tuple[dict, str | None]:
    card_number = "".join(str(payload.get("card_number", "")).split())
    card_holder_name = str(payload.get("card_holder_name", "")).strip()
    card_type = str(payload.get("card_type", "")).strip().upper()
    expiry_month = payload.get("expiry_month")
    expiry_year = payload.get("expiry_year")

    if not card_number:
        return {}, "card_number is required."
    if not card_number.isdigit() or not 12 <= len(card_number) <= 19:
        return {}, "card_number must contain 12 to 19 digits."
    if not _passes_luhn_check(card_number):
        return {}, "card_number is invalid."
    if not card_holder_name:
        return {}, "card_holder_name is required."
    if len(card_holder_name) > 100:
        return {}, "card_holder_name must be 100 characters or fewer."
    if card_type not in {choice.value for choice in SavedCard.CardType}:
        return {}, "card_type must be CREDIT or DEBIT."

    try:
        expiry_month = int(expiry_month)
        expiry_year = int(expiry_year)
    except (TypeError, ValueError):
        return {}, "expiry_month and expiry_year must be numbers."

    if not 1 <= expiry_month <= 12:
        return {}, "expiry_month must be between 1 and 12."
    today = timezone.localdate()
    if expiry_year < today.year:
        return {}, "expiry_year must be this year or later."
    if expiry_year > today.year + 30:
        return {}, "expiry_year is too far in the future."
    if expiry_year == today.year and expiry_month < today.month:
        return {}, "Card has expired."

    last4 = card_number[-4:]
    return {
        "card_holder_name": card_holder_name,
        "card_type": card_type,
        "masked_card_number": f"{'*' * (len(card_number) - 4)}{last4}",
        "last4": last4,
        "expiry_month": expiry_month,
        "expiry_year": expiry_year,
    }, None


def _passes_luhn_check(card_number: str) -> bool:
    total = 0
    reverse_digits = card_number[::-1]
    for index, character in enumerate(reverse_digits):
        digit = int(character)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0

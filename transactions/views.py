from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from transactions.models import Transaction
from transactions.serializers import serialize_transaction


@require_GET
def transaction_history(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)

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
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)

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
    try:
        return Decimal(value)
    except InvalidOperation:
        return None

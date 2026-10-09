import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import django
from django.apps import apps

from models import PaymentRequest, PaymentResponse, Transaction, TransactionStatus


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "transaction_project.settings")
if not apps.ready:
    django.setup()

from django.contrib.auth import get_user_model
from transactions.models import Transaction as TransactionRecord


class UserNotFoundError(ValueError):
    pass


def process_payment(payment: PaymentRequest, user=None) -> PaymentResponse:
    user = user or _get_user(payment.user_id)
    if user.id != payment.user_id:
        raise PermissionError("Authenticated user cannot create payments for another user.")
    transaction = _create_pending_transaction(payment)

    final_status, message = _simulate_payment_processing(payment)
    transaction.status = final_status
    transaction.message = message
    transaction.updated_at = datetime.now(UTC)

    TransactionRecord.objects.create(
        transaction_id=transaction.transaction_id,
        user=user,
        amount=transaction.amount,
        currency=transaction.currency,
        status=transaction.status,
        masked_card_number=transaction.masked_card_number,
        message=transaction.message,
    )

    return PaymentResponse(**transaction.model_dump())


def get_transaction_by_id(transaction_id: str, user=None) -> Transaction | None:
    filters = {"transaction_id": transaction_id}
    if user is not None:
        filters["user"] = user
    try:
        record = TransactionRecord.objects.get(**filters)
    except TransactionRecord.DoesNotExist:
        return None
    return _record_to_transaction(record)


def get_all_transactions(user=None) -> list[Transaction]:
    records = TransactionRecord.objects.all()
    if user is not None:
        records = records.filter(user=user)
    return [_record_to_transaction(record) for record in records]


def _get_user(user_id: int):
    user_model = get_user_model()
    try:
        return user_model.objects.get(id=user_id)
    except user_model.DoesNotExist as exc:
        raise UserNotFoundError(f"User with id {user_id} was not found.") from exc


def _create_pending_transaction(payment: PaymentRequest) -> Transaction:
    timestamp = datetime.now(UTC)
    return Transaction(
        transaction_id=str(uuid4()),
        amount=payment.amount,
        currency=payment.currency,
        status=TransactionStatus.PENDING,
        message="Payment is pending processing.",
        created_at=timestamp,
        updated_at=timestamp,
        masked_card_number=_mask_card_number(payment.card.card_number),
    )


def _simulate_payment_processing(payment: PaymentRequest) -> tuple[TransactionStatus, str]:
    # Deterministic demo rules keep API behavior easy to test and explain.
    if payment.amount > Decimal("50000.00"):
        return TransactionStatus.FAILED, "Payment failed: amount exceeds processor limit."
    if payment.card.card_number.endswith("0000"):
        return TransactionStatus.FAILED, "Payment failed: card was declined by processor."
    return TransactionStatus.SUCCESS, "Payment processed successfully."


def _mask_card_number(card_number: str) -> str:
    return f"{'*' * (len(card_number) - 4)}{card_number[-4:]}"


def _record_to_transaction(record: TransactionRecord) -> Transaction:
    return Transaction(
        transaction_id=str(record.transaction_id),
        amount=record.amount,
        currency=record.currency,
        status=TransactionStatus(record.status),
        message=record.message,
        created_at=record.created_at,
        updated_at=record.updated_at,
        masked_card_number=record.masked_card_number,
    )

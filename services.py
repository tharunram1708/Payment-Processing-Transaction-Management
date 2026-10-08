from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from models import PaymentRequest, PaymentResponse, Transaction, TransactionStatus


transactions: dict[str, Transaction] = {}


def process_payment(payment: PaymentRequest) -> PaymentResponse:
    transaction = _create_pending_transaction(payment)
    transactions[transaction.transaction_id] = transaction

    final_status, message = _simulate_payment_processing(payment)
    transaction.status = final_status
    transaction.message = message
    transaction.updated_at = datetime.now(UTC)

    return PaymentResponse(**transaction.model_dump())


def get_transaction_by_id(transaction_id: str) -> Transaction | None:
    return transactions.get(transaction_id)


def get_all_transactions() -> list[Transaction]:
    return list(transactions.values())


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

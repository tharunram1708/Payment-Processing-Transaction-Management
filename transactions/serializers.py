from transactions.models import Transaction


def serialize_transaction(transaction: Transaction) -> dict[str, str]:
    return {
        "transaction_id": str(transaction.transaction_id),
        "amount": str(transaction.amount),
        "currency": transaction.currency,
        "status": transaction.status,
        "masked_card_number": transaction.masked_card_number,
        "message": transaction.message,
        "created_at": transaction.created_at.isoformat(),
        "updated_at": transaction.updated_at.isoformat(),
    }

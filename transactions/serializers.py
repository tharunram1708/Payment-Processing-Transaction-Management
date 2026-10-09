from transactions.models import SavedCard, Transaction


def serialize_user(user) -> dict[str, str]:
    return {
        "id": user.id,
        "username": user.get_username(),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


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


def serialize_saved_card(card: SavedCard) -> dict[str, str | int]:
    return {
        "id": card.id,
        "card_holder_name": card.card_holder_name,
        "card_type": card.card_type,
        "masked_card_number": card.masked_card_number,
        "last4": card.last4,
        "expiry_month": card.expiry_month,
        "expiry_year": card.expiry_year,
        "created_at": card.created_at.isoformat(),
    }

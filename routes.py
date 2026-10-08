from fastapi import APIRouter, HTTPException, status

from models import PaymentRequest, PaymentResponse, Transaction
from services import get_all_transactions, get_transaction_by_id, process_payment


router = APIRouter()


@router.get("/", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "Payment Processing API is running"}


@router.post(
    "/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Payments"],
    summary="Make a payment",
)
def make_payment(payment: PaymentRequest) -> PaymentResponse:
    return process_payment(payment)


@router.get(
    "/transactions/{transaction_id}",
    response_model=Transaction,
    tags=["Transactions"],
    summary="Get transaction details",
)
def get_transaction(transaction_id: str) -> Transaction:
    transaction = get_transaction_by_id(transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )
    return transaction


@router.get(
    "/transactions",
    response_model=list[Transaction],
    tags=["Transactions"],
    summary="List transactions",
)
def list_transactions() -> list[Transaction]:
    return get_all_transactions()

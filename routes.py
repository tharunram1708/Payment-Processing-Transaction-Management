from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from django.contrib.auth import get_user_model

from models import PaymentRequest, PaymentResponse, Transaction
from services import UserNotFoundError, get_all_transactions, get_transaction_by_id, process_payment
from transactions.authentication import TokenError, decode_access_token
from transactions.models import RevokedToken


router = APIRouter()
bearer_auth = HTTPBearer(auto_error=False)


def authenticated_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth)):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
        if RevokedToken.objects.filter(jti=payload["jti"]).exists():
            raise TokenError("Token has been revoked.")
        return get_user_model().objects.get(pk=payload["sub"], is_active=True)
    except (TokenError, get_user_model().DoesNotExist) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc) or "Authentication failed.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


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
def make_payment(payment: PaymentRequest, user=Depends(authenticated_user)) -> PaymentResponse:
    try:
        return process_payment(payment, user=user)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get(
    "/transactions/{transaction_id}",
    response_model=Transaction,
    tags=["Transactions"],
    summary="Get transaction details",
)
def get_transaction(transaction_id: str, user=Depends(authenticated_user)) -> Transaction:
    transaction = get_transaction_by_id(transaction_id, user=user)
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
def list_transactions(user=Depends(authenticated_user)) -> list[Transaction]:
    return get_all_transactions(user=user)

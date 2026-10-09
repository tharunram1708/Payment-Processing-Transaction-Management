from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class CardDetails(BaseModel):
    card_number: str = Field(
        ...,
        min_length=12,
        max_length=19,
        examples=["4111111111111111"],
        description="Payment card number. Spaces and hyphens are accepted.",
    )
    card_holder_name: str = Field(..., min_length=2, max_length=100, examples=["Tharun Kumar"])
    expiry_month: int = Field(..., ge=1, le=12, examples=[12])
    expiry_year: int = Field(..., ge=2000, le=2100, examples=[2030])
    cvv: str = Field(..., min_length=3, max_length=4, pattern=r"^\d{3,4}$", examples=["123"])

    @field_validator("card_number")
    @classmethod
    def validate_card_number(cls, value: str) -> str:
        normalized = value.replace(" ", "").replace("-", "")
        if not normalized.isdigit():
            raise ValueError("card_number must contain only digits, spaces, or hyphens")
        if not _passes_luhn_check(normalized):
            raise ValueError("card_number is invalid")
        return normalized

    @field_validator("card_holder_name")
    @classmethod
    def validate_card_holder_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("card_holder_name is required")
        return normalized

    @model_validator(mode="after")
    def validate_expiry_date(self) -> "CardDetails":
        now = datetime.now(UTC)
        if self.expiry_year < now.year or (
            self.expiry_year == now.year and self.expiry_month < now.month
        ):
            raise ValueError("card expiry date must be in the future")
        return self


class PaymentRequest(BaseModel):
    user_id: int = Field(..., gt=0, examples=[1], description="Django user ID that owns this payment.")
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2, examples=["1499.00"])
    currency: str = Field(..., min_length=3, max_length=3, examples=["INR"])
    card: CardDetails

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("currency must be a 3-letter ISO code")
        return value.upper()


class PaymentResponse(BaseModel):
    transaction_id: str
    amount: Decimal
    currency: str
    status: TransactionStatus
    message: str
    created_at: datetime
    updated_at: datetime


class Transaction(PaymentResponse):
    masked_card_number: str


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

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from transactions.models import Transaction


class TransactionApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="user1", password="pass12345")
        self.other_user = user_model.objects.create_user(username="user2", password="pass12345")
        self.transaction = Transaction.objects.create(
            user=self.user,
            amount=Decimal("1499.00"),
            currency="INR",
            status=Transaction.PaymentStatus.SUCCESS,
            masked_card_number="************1111",
            message="Payment processed successfully.",
        )
        Transaction.objects.create(
            user=self.other_user,
            amount=Decimal("999.00"),
            currency="INR",
            status=Transaction.PaymentStatus.FAILED,
            masked_card_number="************2222",
            message="Payment failed.",
        )

    def test_history_requires_authentication(self):
        response = self.client.get(reverse("transaction-history"))

        self.assertEqual(response.status_code, 401)

    def test_history_returns_only_own_transactions(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("transaction-history"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["transactions"][0]["transaction_id"], str(self.transaction.transaction_id))

    def test_details_returns_only_own_transaction(self):
        self.client.force_login(self.other_user)

        response = self.client.get(
            reverse("transaction-details", kwargs={"transaction_id": self.transaction.transaction_id})
        )

        self.assertEqual(response.status_code, 404)

    def test_history_filters_by_status_and_amount(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("transaction-history"),
            {"payment_status": "SUCCESS", "amount": "1499.00"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_history_filters_by_date(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("transaction-history"),
            {"date": timezone.localdate().isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from models import PaymentRequest
from routes import authenticated_user
from routes import get_transaction as fastapi_get_transaction
from routes import list_transactions as fastapi_list_transactions
from routes import make_payment as fastapi_make_payment
from services import UserNotFoundError, get_transaction_by_id, process_payment
from transactions.authentication import TokenError, create_access_token, decode_access_token
from transactions.models import AdminActivityLog, RevokedToken, SavedCard, Transaction


class TransactionApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="user1", password="pass12345")
        self.other_user = user_model.objects.create_user(username="user2", password="pass12345")
        self.admin_user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass12345",
        )
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

    def test_details_returns_owned_transaction(self):
        token = self._login_token("user1", "pass12345")

        response = self.client.get(
            reverse("transaction-details", kwargs={"transaction_id": self.transaction.transaction_id}),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transaction_id"], str(self.transaction.transaction_id))

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

    def test_history_rejects_malformed_amount_filter(self):
        token = self._login_token("user1", "pass12345")

        response = self.client.get(
            reverse("transaction-history"),
            {"amount": "1499.00 OR 1=1"},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "amount must be a valid decimal.")

    def test_history_rejects_invalid_status_and_date_filters(self):
        token = self._login_token("user1", "pass12345")

        bad_status_response = self.client.get(
            reverse("transaction-history"),
            {"status": "PAID"},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        bad_date_response = self.client.get(
            reverse("transaction-history"),
            {"date": "2026-99-99"},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(bad_status_response.status_code, 400)
        self.assertEqual(bad_status_response.json()["detail"], "status must be one of PENDING, SUCCESS, or FAILED.")
        self.assertEqual(bad_date_response.status_code, 400)
        self.assertEqual(bad_date_response.json()["detail"], "date must use YYYY-MM-DD format.")

    def test_registration_creates_user_with_hashed_password_and_token(self):
        response = self.client.post(
            reverse("auth-register"),
            data=json.dumps(
                {
                    "username": "new-user",
                    "email": "new-user@example.com",
                    "password": "StrongPass12345",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("access_token", data)

        user = get_user_model().objects.get(username="new-user")
        self.assertNotEqual(user.password, "StrongPass12345")
        self.assertTrue(user.check_password("StrongPass12345"))

    def test_registration_rejects_invalid_json_and_weak_password(self):
        invalid_json_response = self.client.post(
            reverse("auth-register"),
            data="{",
            content_type="application/json",
        )
        weak_password_response = self.client.post(
            reverse("auth-register"),
            data=json.dumps({"username": "weak-user", "password": "123"}),
            content_type="application/json",
        )

        self.assertEqual(invalid_json_response.status_code, 400)
        self.assertEqual(invalid_json_response.json()["detail"], "Request body must be valid JSON.")
        self.assertEqual(weak_password_response.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(username="weak-user").exists())

    def test_login_returns_jwt_and_protected_user_route_accepts_it(self):
        login_response = self.client.post(
            reverse("auth-login"),
            data=json.dumps({"username": "user1", "password": "pass12345"}),
            content_type="application/json",
        )

        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["access_token"]

        me_response = self.client.get(reverse("auth-me"), HTTP_AUTHORIZATION=f"Bearer {token}")

        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["user"]["username"], "user1")

    def test_login_rejects_invalid_credentials(self):
        response = self.client.post(
            reverse("auth-login"),
            data=json.dumps({"username": "user1", "password": "wrong-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid username or password.")

    def test_transaction_history_accepts_jwt_authentication(self):
        token = self._login_token("user1", "pass12345")

        response = self.client.get(reverse("transaction-history"), HTTP_AUTHORIZATION=f"Bearer {token}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_logout_revokes_jwt(self):
        token = self._login_token("user1", "pass12345")

        logout_response = self.client.post(reverse("auth-logout"), HTTP_AUTHORIZATION=f"Bearer {token}")

        self.assertEqual(logout_response.status_code, 200)
        self.assertEqual(RevokedToken.objects.count(), 1)

        me_response = self.client.get(reverse("auth-me"), HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(me_response.status_code, 401)
        self.assertEqual(me_response.json()["detail"], "Token has been revoked.")

    @override_settings(JWT_ACCESS_TOKEN_LIFETIME=timedelta(seconds=-1))
    def test_expired_jwt_is_rejected(self):
        token, _ = create_access_token(self.user)

        with self.assertRaises(TokenError):
            decode_access_token(token)

        response = self.client.get(reverse("auth-me"), HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Token has expired.")

    def test_add_card_stores_only_masked_card_and_last4(self):
        token = self._login_token("user1", "pass12345")
        full_card_number = "4111111111111111"

        response = self.client.post(
            reverse("saved-cards"),
            data=json.dumps(
                {
                    "card_number": full_card_number,
                    "card_holder_name": "Tharun Kumar",
                    "card_type": "credit",
                    "expiry_month": 12,
                    "expiry_year": timezone.localdate().year + 1,
                    "cvv": "123",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()["card"]
        self.assertEqual(data["masked_card_number"], "************1111")
        self.assertEqual(data["last4"], "1111")
        self.assertNotIn("card_number", data)
        self.assertNotIn(full_card_number, json.dumps(data))

        card = SavedCard.objects.get(user=self.user)
        self.assertEqual(card.masked_card_number, "************1111")
        self.assertEqual(card.last4, "1111")
        self.assertFalse(hasattr(card, "card_number"))
        self.assertFalse(hasattr(card, "cvv"))

    def test_add_card_rejects_invalid_card_number(self):
        token = self._login_token("user1", "pass12345")

        response = self.client.post(
            reverse("saved-cards"),
            data=json.dumps(
                {
                    "card_number": "4111111111111112",
                    "card_holder_name": "Tharun Kumar",
                    "card_type": "credit",
                    "expiry_month": 12,
                    "expiry_year": timezone.localdate().year + 1,
                    "cvv": "123",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "card_number is invalid.")
        self.assertFalse(SavedCard.objects.filter(user=self.user).exists())

    def test_add_card_rejects_invalid_card_type_and_expired_card(self):
        token = self._login_token("user1", "pass12345")

        invalid_type_response = self.client.post(
            reverse("saved-cards"),
            data=json.dumps(
                {
                    "card_number": "4111111111111111",
                    "card_holder_name": "Tharun Kumar",
                    "card_type": "prepaid",
                    "expiry_month": 12,
                    "expiry_year": timezone.localdate().year + 1,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        expired_card_response = self.client.post(
            reverse("saved-cards"),
            data=json.dumps(
                {
                    "card_number": "4111111111111111",
                    "card_holder_name": "Tharun Kumar",
                    "card_type": "credit",
                    "expiry_month": 1,
                    "expiry_year": timezone.localdate().year - 1,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(invalid_type_response.status_code, 400)
        self.assertEqual(invalid_type_response.json()["detail"], "card_type must be CREDIT or DEBIT.")
        self.assertEqual(expired_card_response.status_code, 400)
        self.assertEqual(expired_card_response.json()["detail"], "expiry_year must be this year or later.")

    def test_view_saved_cards_returns_only_own_cards(self):
        token = self._login_token("user1", "pass12345")
        SavedCard.objects.create(
            user=self.user,
            card_holder_name="User One",
            card_type=SavedCard.CardType.DEBIT,
            masked_card_number="************4444",
            last4="4444",
            expiry_month=1,
            expiry_year=timezone.localdate().year + 1,
        )
        SavedCard.objects.create(
            user=self.other_user,
            card_holder_name="User Two",
            card_type=SavedCard.CardType.CREDIT,
            masked_card_number="************5555",
            last4="5555",
            expiry_month=2,
            expiry_year=timezone.localdate().year + 1,
        )

        response = self.client.get(reverse("saved-cards"), HTTP_AUTHORIZATION=f"Bearer {token}")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["cards"][0]["last4"], "4444")

    def test_delete_saved_card_deletes_only_owned_card(self):
        token = self._login_token("user1", "pass12345")
        other_card = SavedCard.objects.create(
            user=self.other_user,
            card_holder_name="User Two",
            card_type=SavedCard.CardType.CREDIT,
            masked_card_number="************5555",
            last4="5555",
            expiry_month=2,
            expiry_year=timezone.localdate().year + 1,
        )
        own_card = SavedCard.objects.create(
            user=self.user,
            card_holder_name="User One",
            card_type=SavedCard.CardType.DEBIT,
            masked_card_number="************4444",
            last4="4444",
            expiry_month=1,
            expiry_year=timezone.localdate().year + 1,
        )

        other_response = self.client.delete(
            reverse("delete-saved-card", kwargs={"card_id": other_card.id}),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        own_response = self.client.delete(
            reverse("delete-saved-card", kwargs={"card_id": own_card.id}),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(other_response.status_code, 404)
        self.assertEqual(own_response.status_code, 200)
        self.assertTrue(SavedCard.objects.filter(id=other_card.id).exists())
        self.assertFalse(SavedCard.objects.filter(id=own_card.id).exists())

    def test_card_template_requires_login(self):
        response = self.client.get(reverse("card-list-page"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login-page"), response["Location"])

    def test_card_template_renders_saved_cards(self):
        self.client.force_login(self.user)
        SavedCard.objects.create(
            user=self.user,
            card_holder_name="User One",
            card_type=SavedCard.CardType.CREDIT,
            masked_card_number="************1111",
            last4="1111",
            expiry_month=12,
            expiry_year=timezone.localdate().year + 1,
        )

        response = self.client.get(reverse("card-list-page"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "transactions/cards.html")
        self.assertContains(response, "************1111")
        self.assertNotContains(response, "4111111111111111")

    def test_card_template_form_adds_masked_card(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("card-list-page"),
            data={
                "card_number": "4111111111111111",
                "card_holder_name": "User One",
                "card_type": "DEBIT",
                "expiry_month": 12,
                "expiry_year": timezone.localdate().year + 1,
            },
        )

        self.assertEqual(response.status_code, 302)
        card = SavedCard.objects.get(user=self.user)
        self.assertEqual(card.masked_card_number, "************1111")
        self.assertEqual(card.last4, "1111")

    def test_admin_daily_summary_requires_admin_login(self):
        response = self.client.get(reverse("admin:transactions_transaction_daily_summary"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_admin_daily_summary_shows_daily_payment_counts_and_amount(self):
        self.client.force_login(self.admin_user)
        Transaction.objects.create(
            user=self.user,
            amount=Decimal("250.00"),
            currency="INR",
            status=Transaction.PaymentStatus.PENDING,
            masked_card_number="************3333",
            message="Payment pending.",
        )

        response = self.client.get(
            reverse("admin:transactions_transaction_daily_summary"),
            {"date": timezone.localdate().isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total transactions")
        self.assertContains(response, "Successful payments")
        self.assertContains(response, "Failed payments")
        self.assertContains(response, "Pending payments")
        self.assertContains(response, "2748.00")
        self.assertTrue(
            AdminActivityLog.objects.filter(
                admin_user=self.admin_user,
                action=AdminActivityLog.Action.VIEWED,
                model_name=Transaction._meta.label,
            ).exists()
        )

    def test_admin_transaction_csv_export_requires_admin_login(self):
        response = self.client.get(reverse("admin:transactions_transaction_export_csv"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_admin_transaction_csv_export_returns_records_and_logs_action(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:transactions_transaction_export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        content = response.content.decode()
        self.assertIn("transaction_id,user_id,username,amount,currency,status", content)
        self.assertIn(str(self.transaction.transaction_id), content)
        self.assertIn("user1", content)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                admin_user=self.admin_user,
                action=AdminActivityLog.Action.EXPORTED,
                model_name=Transaction._meta.label,
            ).exists()
        )

    def test_fastapi_payment_creates_django_transaction_for_user(self):
        payment = self._payment_request(user_id=self.user.id)

        response = process_payment(payment)

        record = Transaction.objects.get(transaction_id=response.transaction_id)
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.amount, Decimal("1499.00"))
        self.assertEqual(record.currency, "INR")
        self.assertEqual(record.status, Transaction.PaymentStatus.SUCCESS)
        self.assertEqual(record.masked_card_number, "************1111")

    def test_fastapi_payment_updates_status_to_failed_for_large_amount(self):
        payment = self._payment_request(user_id=self.user.id, amount=Decimal("50000.01"))

        response = process_payment(payment)

        record = Transaction.objects.get(transaction_id=response.transaction_id)
        self.assertEqual(response.status, Transaction.PaymentStatus.FAILED)
        self.assertEqual(record.status, Transaction.PaymentStatus.FAILED)
        self.assertEqual(record.message, "Payment failed: amount exceeds processor limit.")

    def test_fastapi_payment_updates_status_to_failed_for_declined_card(self):
        payment = self._payment_request(user_id=self.user.id, card_number="4000000000020000")

        response = process_payment(payment)

        record = Transaction.objects.get(transaction_id=response.transaction_id)
        self.assertEqual(response.status, Transaction.PaymentStatus.FAILED)
        self.assertEqual(record.status, Transaction.PaymentStatus.FAILED)
        self.assertEqual(record.message, "Payment failed: card was declined by processor.")

    def test_fastapi_transaction_lookup_reads_django_database(self):
        transaction = get_transaction_by_id(str(self.transaction.transaction_id))

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.transaction_id, str(self.transaction.transaction_id))
        self.assertEqual(transaction.status, Transaction.PaymentStatus.SUCCESS)

    def test_fastapi_payment_requires_existing_django_user(self):
        payment = self._payment_request(user_id=999999)

        with self.assertRaises(UserNotFoundError):
            process_payment(payment)

    def test_fastapi_transaction_list_requires_jwt(self):
        with self.assertRaises(HTTPException) as exc:
            authenticated_user(None)

        self.assertEqual(exc.exception.status_code, 401)

    def test_fastapi_transaction_list_returns_only_authenticated_users_records(self):
        data = fastapi_list_transactions(user=self.user)

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0].transaction_id, str(self.transaction.transaction_id))

    def test_fastapi_transaction_detail_rejects_other_users_record(self):
        with self.assertRaises(HTTPException) as exc:
            fastapi_get_transaction(str(self.transaction.transaction_id), user=self.other_user)

        self.assertEqual(exc.exception.status_code, 404)

    def test_fastapi_payment_rejects_cross_user_payment_creation(self):
        payment = PaymentRequest(**self._fastapi_payment_payload(user_id=self.other_user.id))

        with self.assertRaises(HTTPException) as exc:
            fastapi_make_payment(payment, user=self.user)

        self.assertEqual(exc.exception.status_code, 403)

    def test_fastapi_payment_stores_masked_card_only(self):
        payment = PaymentRequest(**self._fastapi_payment_payload(user_id=self.user.id))

        response = fastapi_make_payment(payment, user=self.user)

        record = Transaction.objects.get(transaction_id=response.transaction_id)
        self.assertEqual(record.masked_card_number, "************1111")
        self.assertNotIn("4111111111111111", str(record.__dict__))
        self.assertNotIn("123", str(record.__dict__))

    def test_fastapi_auth_dependency_accepts_valid_jwt(self):
        user = authenticated_user(self._fastapi_credentials(self.user))

        self.assertEqual(user, self.user)

    def test_fastapi_auth_dependency_rejects_revoked_jwt(self):
        token, payload = create_access_token(self.user)
        RevokedToken.objects.create(
            jti=payload["jti"],
            user=self.user,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with self.assertRaises(HTTPException) as exc:
            authenticated_user(credentials)

        self.assertEqual(exc.exception.status_code, 401)
        self.assertEqual(exc.exception.detail, "Token has been revoked.")

    def _payment_request(
        self,
        user_id: int,
        amount: Decimal = Decimal("1499.00"),
        card_number: str = "4111111111111111",
    ) -> PaymentRequest:
        return PaymentRequest(
            user_id=user_id,
            amount=amount,
            currency="inr",
            card={
                "card_number": card_number,
                "card_holder_name": "Tharun Kumar",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
            },
        )

    def _login_token(self, username: str, password: str) -> str:
        response = self.client.post(
            reverse("auth-login"),
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def _fastapi_credentials(self, user) -> HTTPAuthorizationCredentials:
        token, _ = create_access_token(user)
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def _fastapi_payment_payload(self, user_id: int) -> dict:
        return {
            "user_id": user_id,
            "amount": "1499.00",
            "currency": "inr",
            "card": {
                "card_number": "4111111111111111",
                "card_holder_name": "Tharun Kumar",
                "expiry_month": 12,
                "expiry_year": timezone.localdate().year + 1,
                "cvv": "123",
            },
        }

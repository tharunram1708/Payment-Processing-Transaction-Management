import csv
from datetime import datetime
from decimal import Decimal

from django.contrib import admin
from django.contrib.admin.exceptions import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from transactions.models import AdminActivityLog, RevokedToken, SavedCard, Transaction


def log_admin_activity(
    request,
    action: str,
    model_name: str,
    obj=None,
    metadata: dict | None = None,
) -> None:
    if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
        return

    AdminActivityLog.objects.create(
        admin_user=request.user,
        action=action,
        model_name=model_name,
        object_id=str(getattr(obj, "pk", "")) if obj is not None else "",
        object_repr=str(obj)[:255] if obj is not None else "",
        metadata=metadata or {},
    )


class AdminActivityLogMixin:
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log_admin_activity(
            request,
            AdminActivityLog.Action.UPDATED if change else AdminActivityLog.Action.CREATED,
            obj._meta.label,
            obj,
        )

    def delete_model(self, request, obj):
        log_admin_activity(
            request,
            AdminActivityLog.Action.DELETED,
            obj._meta.label,
            obj,
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        model_name = queryset.model._meta.label
        count = queryset.count()
        log_admin_activity(
            request,
            AdminActivityLog.Action.DELETED,
            model_name,
            metadata={"count": count},
        )
        super().delete_queryset(request, queryset)


UserModel = get_user_model()


class SavedCardInline(admin.TabularInline):
    model = SavedCard
    extra = 0
    fields = ("card_type", "masked_card_number", "last4", "expiry_month", "expiry_year", "created_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 0
    fields = ("transaction_id", "amount", "currency", "status", "masked_card_number", "created_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


try:
    admin.site.unregister(UserModel)
except NotRegistered:
    pass


@admin.register(UserModel)
class ManagedUserAdmin(AdminActivityLogMixin, UserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "card_count",
        "transaction_count",
    )
    list_filter = UserAdmin.list_filter + ("date_joined",)
    search_fields = ("username", "email", "first_name", "last_name")
    inlines = (SavedCardInline, TransactionInline)

    @admin.display(description="Cards")
    def card_count(self, obj):
        return obj.saved_cards.count()

    @admin.display(description="Transactions")
    def transaction_count(self, obj):
        return obj.transactions.count()


@admin.register(Transaction)
class TransactionAdmin(AdminActivityLogMixin, admin.ModelAdmin):
    change_list_template = "admin/transactions/transaction/change_list.html"
    actions = ("export_transactions_csv",)
    list_display = (
        "transaction_id",
        "user",
        "amount",
        "currency",
        "status",
        "masked_card_number",
        "created_at",
    )
    list_filter = ("status", "currency", "created_at")
    date_hierarchy = "created_at"
    readonly_fields = ("transaction_id", "created_at", "updated_at")
    search_fields = ("transaction_id", "user__username", "user__email", "masked_card_number")

    def get_urls(self):
        custom_urls = [
            path(
                "daily-summary/",
                self.admin_site.admin_view(self.daily_summary_view),
                name="transactions_transaction_daily_summary",
            ),
            path(
                "export-csv/",
                self.admin_site.admin_view(self.export_csv_view),
                name="transactions_transaction_export_csv",
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.action(description="Export selected transactions to CSV")
    def export_transactions_csv(self, request, queryset):
        log_admin_activity(
            request,
            AdminActivityLog.Action.EXPORTED,
            Transaction._meta.label,
            metadata={"count": queryset.count(), "scope": "selected"},
        )
        return self._transactions_csv_response(queryset)

    def export_csv_view(self, request):
        queryset = self.get_queryset(request)
        log_admin_activity(
            request,
            AdminActivityLog.Action.EXPORTED,
            Transaction._meta.label,
            metadata={"count": queryset.count(), "scope": "all"},
        )
        return self._transactions_csv_response(queryset)

    def daily_summary_view(self, request):
        selected_date, date_error = self._summary_date(request.GET.get("date"))
        queryset = self.get_queryset(request).filter(created_at__date=selected_date)
        total_amount = queryset.aggregate(total_amount=Sum("amount"))["total_amount"] or Decimal("0.00")
        summary = queryset.aggregate(
            total_transactions=Count("id"),
            successful_payments=Count("id", filter=Q(status=Transaction.PaymentStatus.SUCCESS)),
            failed_payments=Count("id", filter=Q(status=Transaction.PaymentStatus.FAILED)),
            pending_payments=Count("id", filter=Q(status=Transaction.PaymentStatus.PENDING)),
        )
        summary["total_payment_amount"] = total_amount

        log_admin_activity(
            request,
            AdminActivityLog.Action.VIEWED,
            Transaction._meta.label,
            metadata={"view": "daily_payment_summary", "date": selected_date.isoformat()},
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "Daily payment summary",
            "opts": self.model._meta,
            "summary": summary,
            "selected_date": selected_date,
            "date_error": date_error,
            "transaction_changelist_url": reverse("admin:transactions_transaction_changelist"),
            "export_url": reverse("admin:transactions_transaction_export_csv"),
        }
        return TemplateResponse(request, "admin/transactions/daily_payment_summary.html", context)

    def _summary_date(self, value):
        if not value:
            return timezone.localdate(), None

        try:
            return datetime.strptime(value, "%Y-%m-%d").date(), None
        except ValueError:
            return timezone.localdate(), "Date must use YYYY-MM-DD format."

    def _transactions_csv_response(self, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="transactions.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "transaction_id",
                "user_id",
                "username",
                "amount",
                "currency",
                "status",
                "masked_card_number",
                "message",
                "created_at",
                "updated_at",
            ]
        )
        for transaction in queryset.select_related("user").order_by("-created_at"):
            writer.writerow(
                [
                    transaction.transaction_id,
                    transaction.user_id,
                    transaction.user.get_username(),
                    transaction.amount,
                    transaction.currency,
                    transaction.status,
                    transaction.masked_card_number,
                    transaction.message,
                    transaction.created_at.isoformat(),
                    transaction.updated_at.isoformat(),
                ]
            )
        return response


@admin.register(RevokedToken)
class RevokedTokenAdmin(admin.ModelAdmin):
    list_display = ("jti", "user", "revoked_at", "expires_at")
    search_fields = ("jti", "user__username")


@admin.register(SavedCard)
class SavedCardAdmin(AdminActivityLogMixin, admin.ModelAdmin):
    list_display = (
        "user",
        "card_holder_name",
        "card_type",
        "masked_card_number",
        "last4",
        "expiry_month",
        "expiry_year",
        "created_at",
    )
    list_filter = ("card_type", "created_at")
    readonly_fields = ("masked_card_number", "last4", "created_at")
    search_fields = ("user__username", "user__email", "card_holder_name", "last4", "masked_card_number")

    def has_add_permission(self, request):
        return False


@admin.register(AdminActivityLog)
class AdminActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "admin_user", "action", "model_name", "object_id", "object_repr")
    list_filter = ("action", "model_name", "created_at")
    readonly_fields = ("admin_user", "action", "model_name", "object_id", "object_repr", "metadata", "created_at")
    search_fields = ("admin_user__username", "model_name", "object_repr", "object_id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

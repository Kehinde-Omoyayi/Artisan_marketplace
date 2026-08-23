"""payments/admin.py — Part 17 Step 3. The human-approval button for large payouts."""

from django.contrib import admin
from django.utils import timezone

from .models import LedgerEntry, Payment, Payout, PayoutLedger, Refund
from .services import PaymentService


@admin.action(description="Approve selected payouts and send transfer")
def approve_and_release(modeladmin, request, queryset):
    for payout in queryset.filter(status="pending_approval"):
        payout.status = "approved"
        payout.approved_by = request.user
        payout.approved_at = timezone.now()
        payout.save()
        PaymentService.release_payout(payout)


class PayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "artisan", "amount_minor", "status", "approved_by", "created_at")
    list_filter = ("status",)
    actions = [approve_and_release]


class PaymentAdmin(admin.ModelAdmin):
    list_display = ("provider_reference", "booking", "amount_minor", "status", "created_at")
    list_filter = ("status", "provider")
    search_fields = ("provider_reference",)


class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_type", "booking", "amount_minor", "reference", "created_at")
    list_filter = ("entry_type",)
    search_fields = ("reference",)


class RefundAdmin(admin.ModelAdmin):
    list_display = ("payment", "amount_minor", "reason", "status", "created_at")
    list_filter = ("status",)


admin.site.register(Payment, PaymentAdmin)
admin.site.register(PayoutLedger)
admin.site.register(LedgerEntry, LedgerEntryAdmin)
admin.site.register(Payout, PayoutAdmin)
admin.site.register(Refund, RefundAdmin)

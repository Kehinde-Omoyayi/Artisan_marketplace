from django.contrib import admin

from .models import AuditLog, FeatureFlag, FeeConfig


class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("key", "is_enabled", "description", "updated_at")
    list_filter = ("is_enabled",)


class FeeConfigAdmin(admin.ModelAdmin):
    list_display = (
        "version",
        "platform_commission_percent",
        "payout_approval_threshold_minor",
        "active",
        "created_at",
    )
    list_filter = ("active",)


class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "target_type", "target_id", "actor", "created_at")
    list_filter = ("action", "target_type")
    search_fields = ("actor", "target_id")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(FeatureFlag, FeatureFlagAdmin)
admin.site.register(FeeConfig, FeeConfigAdmin)
admin.site.register(AuditLog, AuditLogAdmin)

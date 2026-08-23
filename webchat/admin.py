from django.contrib import admin

from .models import PhoneVerificationCode, WebChatMessage, WebChatSession


@admin.register(WebChatSession)
class WebChatSessionAdmin(admin.ModelAdmin):
    list_display = ("session_key", "user", "created_at", "last_seen_at")
    search_fields = ("session_key", "user__phone_e164", "user__full_name")
    readonly_fields = ("session_key", "user", "created_at", "last_seen_at")

    def has_add_permission(self, request):
        return False


@admin.register(PhoneVerificationCode)
class PhoneVerificationCodeAdmin(admin.ModelAdmin):
    # Never expose code_hash/salt as editable — there's nothing a staff member
    # should ever legitimately change on a verification attempt after the fact.
    list_display = ("phone_e164", "session_key", "attempts", "consumed_at", "expires_at", "created_at")
    readonly_fields = list_display
    search_fields = ("phone_e164", "session_key")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(WebChatMessage)
class WebChatMessageAdmin(admin.ModelAdmin):
    """Read-only transcript viewer — useful for support staff investigating a
    dispute or a "the bot didn't reply" report."""

    list_display = ("phone_e164", "direction", "kind", "body", "created_at")
    list_filter = ("direction", "kind")
    search_fields = ("phone_e164", "body")
    readonly_fields = ("phone_e164", "direction", "body", "kind", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

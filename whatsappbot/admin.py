from django.contrib import admin

from .models import ConversationState, WhatsAppMessage


class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ("phone_e164", "direction", "created_at")
    list_filter = ("direction",)
    search_fields = ("phone_e164",)


class ConversationStateAdmin(admin.ModelAdmin):
    list_display = ("phone_e164", "state", "updated_at")
    list_filter = ("state",)
    search_fields = ("phone_e164",)


admin.site.register(WhatsAppMessage, WhatsAppMessageAdmin)
admin.site.register(ConversationState, ConversationStateAdmin)

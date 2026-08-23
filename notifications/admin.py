from django.contrib import admin

from .models import NotificationLog


class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "template_name", "status", "created_at")
    list_filter = ("channel", "status")


admin.site.register(NotificationLog, NotificationLogAdmin)

from django.contrib import admin

from .models import SupportCase, SupportNote

admin.site.register(SupportNote)


# --- V2 addition, Part 9 Step 2 ---
class SupportCaseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "subject",
        "booking",
        "status",
        "priority",
        "assigned_to",
        "created_at",
    )
    list_filter = ("status", "priority")


admin.site.register(SupportCase, SupportCaseAdmin)

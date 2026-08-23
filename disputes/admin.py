from django.contrib import admin
from django.utils.html import format_html

from .models import Dispute, DisputeEvidence


class DisputeAdmin(admin.ModelAdmin):
    list_display = (
        "booking",
        "reason_code",
        "status",
        "priority",
        "assigned_to",
        "created_at",
    )
    list_filter = ("status", "priority", "reason_code")


class DisputeEvidenceAdmin(admin.ModelAdmin):
    list_display = ("dispute", "uploaded_by", "note", "created_at")
    readonly_fields = ("signed_evidence_link",)

    @admin.display(description="Evidence (link valid 5 minutes)")
    def signed_evidence_link(self, obj):
        if not obj or not obj.storage_key:
            return "—"
        try:
            from core.storage import generate_signed_url

            url = generate_signed_url(obj.storage_key)
        except Exception as exc:  # noqa: BLE001
            return f"Storage not available: {exc}"
        return format_html('<a href="{}" target="_blank" rel="noopener">Open evidence</a>', url)


admin.site.register(Dispute, DisputeAdmin)
admin.site.register(DisputeEvidence, DisputeEvidenceAdmin)

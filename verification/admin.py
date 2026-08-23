from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import VerificationDocument


@admin.action(description="Approve selected documents and raise artisan's verification level")
def approve_documents(modeladmin, request, queryset):
    from core.services import log_audit

    for doc in queryset.filter(status="pending"):
        doc.status = "approved"
        doc.reviewed_by = request.user
        doc.reviewed_at = timezone.now()
        doc.save()

        profile = doc.artisan.artisan_profile
        # "L2" < "L3" < "L4" as plain strings — intentional and simple.
        if doc.level > profile.verification_level:
            profile.verification_level = doc.level
            profile.save()

        log_audit(actor=str(request.user), action="verification_approved", target=doc)


@admin.action(description="Reject selected documents")
def reject_documents(modeladmin, request, queryset):
    from core.services import log_audit

    for doc in queryset.filter(status="pending"):
        doc.status = "rejected"
        doc.reviewed_by = request.user
        doc.reviewed_at = timezone.now()
        doc.save()
        log_audit(actor=str(request.user), action="verification_rejected", target=doc)


class VerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ("artisan", "level", "status", "reviewed_by", "created_at")
    list_filter = ("level", "status")
    actions = [approve_documents, reject_documents]
    readonly_fields = ("signed_document_link",)

    @admin.display(description="Document (link valid 5 minutes)")
    def signed_document_link(self, obj):
        """
        Part 18.2 — the ONLY way staff ever view a document. The bucket stays private;
        this link dies after five minutes.
        """
        if not obj or not obj.storage_key:
            return "—"
        try:
            from core.storage import generate_signed_url

            url = generate_signed_url(obj.storage_key)
        except Exception as exc:  # noqa: BLE001 — storage not configured yet is fine
            return f"Storage not available: {exc}"
        return format_html('<a href="{}" target="_blank" rel="noopener">Open document</a>', url)


admin.site.register(VerificationDocument, VerificationDocumentAdmin)

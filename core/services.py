"""core/services.py — Part 13 Step 2. The one shared audit helper."""

from .models import AuditLog


def log_audit(actor, action, target, metadata=None):
    AuditLog.objects.create(
        actor=str(actor),
        action=action,
        target_type=target.__class__.__name__,
        target_id=str(target.pk),
        metadata=metadata or {},
    )

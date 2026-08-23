"""
Part 11 Step 4 — the three staff roles, as code instead of 20 minutes of clicking.

The manual walks you through building `finance_staff`, `verification_staff` and
`support_staff` by hand in /admin. That works, but it is easy to mis-click a permission
and quietly hand a verification reviewer the ability to approve payouts. This command
builds exactly the same three groups, deterministically, and is safe to re-run.

    python manage.py setup_staff_roles

Least privilege is enforced by Django Admin automatically: a verification_staff user
who opens /admin simply will not see the Payouts page in the menu.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

ROLES = {
    "finance_staff": {
        "payments": ["payment", "ledgerentry", "payout", "refund", "payoutledger"],
        "core": ["feeconfig"],
    },
    "verification_staff": {
        "verification": ["verificationdocument"],
    },
    "support_staff": {
        "disputes": ["dispute", "disputeevidence"],
        "support_app": ["supportcase", "supportnote"],
        "accounts": ["accountaction"],
    },
}

# Nobody gets delete. Deletion of financial or evidentiary records is a superuser action.
ACTIONS = ("view", "add", "change")


class Command(BaseCommand):
    help = "Create/refresh the finance_staff, verification_staff and support_staff groups."

    def handle(self, *args, **options):
        for group_name, app_models in ROLES.items():
            group, created = Group.objects.get_or_create(name=group_name)
            perms = []
            for app_label, models in app_models.items():
                for model in models:
                    for action in ACTIONS:
                        codename = f"{action}_{model}"
                        perm = Permission.objects.filter(
                            codename=codename,
                            content_type__app_label=app_label,
                        ).first()
                        if perm:
                            perms.append(perm)
                        else:
                            self.stderr.write(
                                f"  ! missing permission {app_label}.{codename} "
                                "(run migrate first)"
                            )
            group.permissions.set(perms)
            group.save()
            verb = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"{verb} {group_name} with {len(perms)} permissions")
            )

        self.stdout.write("")
        self.stdout.write(
            "Now create real staff logins in /admin -> Users -> Add user: "
            "uncheck Superuser, check Staff, add to exactly ONE of these groups."
        )

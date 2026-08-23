from django.contrib.gis.db import models as gis_models
from django.db import models


class User(models.Model):
    ROLE_CHOICES = [
        ("customer", "Customer"),
        ("artisan", "Artisan"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("restricted", "Restricted"),
        ("suspended", "Suspended"),
    ]

    phone_e164 = models.CharField(max_length=20, unique=True, db_index=True)
    full_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="customer")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    email = models.EmailField(blank=True, null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.full_name or self.phone_e164} ({self.role})"


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="customer_profile", unique=True
    )
    default_area = models.CharField(max_length=100, blank=True)
    # --- V2 addition: repeat-customer prefetch (Part 24) ---
    # Filled in automatically after each completed request. Lets the bot skip
    # re-asking for area + GPS pin on the customer's next request.
    saved_location = gis_models.PointField(
        geography=True, srid=4326, null=True, blank=True
    )
    total_requests = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Customer profile — {self.user}"


class ArtisanProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="artisan_profile",unique=True
    )
    business_name = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True)
    years_experience = models.PositiveSmallIntegerField(default=0)
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    completed_jobs = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_founder_vetted = models.BooleanField(default=False)
    # --- V2 (Part 6 Step 1). L0 phone linked, L1 profile complete, L2 government ID,
    # L3 service-area/address, L4 skill reference. Every new artisan starts at L0.
    verification_level = models.CharField(max_length=10, default="L0")
    bank_account_number = models.CharField(max_length=20, blank=True, null=True, unique=True)
    bank_code = models.CharField(max_length=10, blank=True)
    bank_account_name = models.CharField(max_length=150, blank=True, null=True, unique=True)
    paystack_recipient_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Artisan profile — {self.user} ({self.verification_level})"


# --- V2 addition, Part 11 Step 1 ---
class AccountAction(models.Model):
    ACTION_CHOICES = [
        ("warn", "Warning"),
        ("restrict", "Restricted"),
        ("suspend", "Suspended"),
        ("reinstate", "Reinstated"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="account_actions"
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    reason = models.TextField()
    actor = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.action} — {self.user}"

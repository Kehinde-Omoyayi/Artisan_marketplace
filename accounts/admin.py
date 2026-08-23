from django.contrib import admin

from .models import AccountAction, ArtisanProfile, CustomerProfile, User


class UserAdmin(admin.ModelAdmin):
    list_display = ("phone_e164", "full_name", "role", "status", "created_at")
    list_filter = ("role", "status")
    search_fields = ("phone_e164", "full_name", "email")


class ArtisanProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "business_name",
        "verification_level",
        "rating_avg",
        "completed_jobs",
        "is_active",
    )
    list_filter = ("verification_level", "is_active", "is_founder_vetted")
    search_fields = ("user__phone_e164", "business_name")


class AccountActionAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "actor", "created_at")
    list_filter = ("action",)


admin.site.register(User, UserAdmin)
admin.site.register(CustomerProfile)
admin.site.register(ArtisanProfile, ArtisanProfileAdmin)
# --- V2 addition, Part 11 Step 2 ---
admin.site.register(AccountAction, AccountActionAdmin)

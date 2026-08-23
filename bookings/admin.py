from django.contrib import admin

from .models import Booking, BookingStatusHistory, ReliabilityEvent


class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "booking_ref",
        "customer",
        "artisan",
        "agreed_amount_minor",
        "status",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("booking_ref", "customer__phone_e164", "artisan__phone_e164")


class BookingStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("booking", "from_status", "to_status", "actor", "created_at")
    list_filter = ("to_status",)


class ReliabilityEventAdmin(admin.ModelAdmin):
    list_display = ("booking", "event_type", "logged_by", "created_at")
    list_filter = ("event_type",)


admin.site.register(Booking, BookingAdmin)
admin.site.register(BookingStatusHistory, BookingStatusHistoryAdmin)
# --- V2 addition, Part 10 Step 2 ---
admin.site.register(ReliabilityEvent, ReliabilityEventAdmin)

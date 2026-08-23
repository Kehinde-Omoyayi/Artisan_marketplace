from django.contrib import admin

from .models import Rating


class RatingAdmin(admin.ModelAdmin):
    list_display = ("artisan", "stars", "rated_by", "booking", "created_at")
    list_filter = ("stars",)


admin.site.register(Rating, RatingAdmin)

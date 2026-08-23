from django.contrib import admin

from .models import ArtisanLocation, AvailabilitySlot, Match, ServiceArea


class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "request",
        "artisan",
        "distance_km",
        "ranking_score",
        "rank_position",
        "ranking_version",
    )
    list_filter = ("ranking_version",)


admin.site.register(ArtisanLocation)
admin.site.register(ServiceArea)
admin.site.register(AvailabilitySlot)
admin.site.register(Match, MatchAdmin)

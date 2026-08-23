from django.contrib import admin

from .models import ArtisanArea, ArtisanService, ServiceCategory


class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "active")
    list_filter = ("active",)
    prepopulated_fields = {"slug": ("name",)}


class ArtisanServiceAdmin(admin.ModelAdmin):
    list_display = ("artisan", "service", "base_price_minor", "active")
    list_filter = ("active", "service")


admin.site.register(ServiceCategory, ServiceCategoryAdmin)
admin.site.register(ArtisanService, ArtisanServiceAdmin)
admin.site.register(ArtisanArea)

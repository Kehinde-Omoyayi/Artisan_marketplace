from django.contrib.gis import admin as gis_admin
from django.contrib import admin

from .models import RequestOffer, ServiceRequest


class ServiceRequestAdmin(gis_admin.GISModelAdmin):
    list_display = ("id", "customer", "category", "area_name", "timing", "status", "created_at")
    list_filter = ("status", "category", "timing")
    search_fields = ("area_name", "customer__phone_e164")


class RequestOfferAdmin(admin.ModelAdmin):
    list_display = ("request", "artisan", "response_status", "created_at")
    list_filter = ("response_status",)


admin.site.register(ServiceRequest, ServiceRequestAdmin)
admin.site.register(RequestOffer, RequestOfferAdmin)

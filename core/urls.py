from django.urls import path

from .views import ReadinessView

urlpatterns = [
    path("readiness/", ReadinessView.as_view(), name="readiness"),
]

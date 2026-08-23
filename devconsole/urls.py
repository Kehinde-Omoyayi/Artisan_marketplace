from django.urls import path

from . import views

urlpatterns = [
    path("state/", views.state, name="dev-state"),
    path("recent/", views.recent, name="dev-recent"),
    path("seed-artisans/", views.seed_artisans, name="dev-seed"),
    path("customer-journey/", views.customer_journey, name="dev-customer"),
    path("artisan-onboarding/", views.artisan_onboarding, name="dev-artisan"),
    path("approve-verification/", views.approve_verification, name="dev-approve"),
    path("money-flow/", views.money_flow, name="dev-money"),
    path("raise-dispute/", views.raise_dispute, name="dev-dispute"),
    path("security-probe/", views.security_probe, name="dev-security"),
    path("infra/", views.infra, name="dev-infra"),
    path("reset/", views.reset, name="dev-reset"),
]

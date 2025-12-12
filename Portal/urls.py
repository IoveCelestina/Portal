# Portal/urls.py
from __future__ import annotations

from django.contrib import admin
from django.urls import path
from django.http import HttpRequest, HttpResponse
from ads.views import AdRecommendView, PortalPageView, PortalAcceptView, PortalPingView


def health_check(request: HttpRequest) -> HttpResponse:
    return HttpResponse("WIFI-Ad-Beacon backend is running.")



urlpatterns = [
    path("admin/", admin.site.urls),
    path("", PortalPageView.as_view(), name="portal-root"),
    path("portal/", PortalPageView.as_view(), name="portal-page"),
    path("api/v1/ad-recommend/", AdRecommendView.as_view(), name="ad-recommend"),
    path("api/v1/portal/accept/", PortalAcceptView.as_view(), name="portal-accept"),
    path("api/v1/portal/ping/", PortalPingView.as_view()),
]


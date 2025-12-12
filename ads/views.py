# ads/views.py
from __future__ import annotations
from typing import Any, Dict
from django.shortcuts import render
from django.views import View
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status

from .models import ClientSession
from .serializers import (
    AdRecommendRequestSerializer,
    AdvertisementSerializer, PortalAcceptResponseSerializer, PortalAcceptSerializer, PortalPingSerializer,
)
from .services import recommend_advertisement_v2, get_client_ip_from_request, mark_client_authenticated, \
    upsert_visit_segment

import logging
logger = logging.getLogger(__name__)


class AdRecommendView(APIView):
    """
    POST /api/v1/ad-recommend/

    请求示例：
    {
      "latitude": 31.2304,
      "longitude": 121.4737,
      "user_agent": "...",
      "local_time": 9
    }

    隐私注意：
    - 不在此视图中记录 request.data 的原始坐标；
      如需日志，请在日志前进行脱敏（例如四舍五入到 2 位小数）。
    """

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AdRecommendRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated = serializer.validated_data

        latitude = validated.get("latitude")
        longitude = validated.get("longitude")
        local_hour = validated.get("local_time")
        user_agent = validated["user_agent"]
        print("ad-recommend lat/lon:", latitude, longitude, "ua:", user_agent[:60])

        logger.info(
            "ad-recommend request lat=%s lon=%s hour=%s ua=%s",
            latitude, longitude, local_hour, user_agent[:80]
        )

        ip = get_client_ip_from_request(request)

        ad = recommend_advertisement_v2(
            latitude=latitude,
            longitude=longitude,
            user_agent=user_agent,
            local_hour=local_hour,
            client_ip=ip,  # 关键：频控按用户区分
        )

        if ad is not None:
            is_geo = bool(ad.target_lat is not None and ad.target_lon is not None and ad.radius_meters is not None)
            logger.info(
                "ad-recommend selected id=%s title=%s is_generic=%s is_geo_target=%s weight=%s",
                ad.id, ad.title, getattr(ad, "is_generic", None), is_geo, getattr(ad, "weight", None)
            )
        else:
            logger.info("ad-recommend selected NONE")

        if ad is None:
            # 没有任何可用广告，返回 204（无内容），或 200 + null 皆可
            return Response(status=status.HTTP_204_NO_CONTENT)

        ad_data = AdvertisementSerializer(ad).data
        return Response(ad_data, status=status.HTTP_200_OK)

class PortalPageView(View):
    def get(self, request):
        return render(request, "portal.html")




class PortalAcceptView(APIView):
    def post(self, request):
        ser = PortalAcceptSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
        ua = request.META.get("HTTP_USER_AGENT", "")

        mark_client_authenticated(
            ip_address=ip,
            user_agent=ua,
            latitude=ser.validated_data.get("latitude"),
            longitude=ser.validated_data.get("longitude"),
            accuracy_m=ser.validated_data.get("accuracy_m"),
        )

        # 读取最新 session（包含 venue 匹配结果）
        session = ClientSession.objects.filter(ip_address=ip).select_related("venue").first()

        payload = {"ok": True}

        if session and session.venue:
            payload["venue"] = {
                "id": session.venue.id,
                "name": session.venue.name,
                "category": session.venue.category,
                "distance_m": session.venue_distance_m,
            }
        else:
            payload["venue"] = None

        return Response(payload, status=status.HTTP_200_OK)


class PortalPingView(APIView):
    """
    POST /api/v1/portal/ping/

    由前端每 60 秒调用一次，用于：
    - 更新 last_seen
    - 按定位匹配 Venue（可选）
    - 维护 VisitSegment 分段轨迹（多店铺停留时长）
    """
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ser = PortalPingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        ip = get_client_ip_from_request(request)
        ua = request.META.get("HTTP_USER_AGENT", "")

        data = ser.validated_data
        result = upsert_visit_segment(
            ip_address=ip,
            user_agent=ua,
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            accuracy_m=data.get("accuracy_m"),
            event=data.get("event"),
        )

        return Response(result, status=status.HTTP_200_OK)

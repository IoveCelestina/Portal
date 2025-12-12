# ads/serializers.py
from __future__ import annotations

from typing import Any, Dict, Optional

from rest_framework import serializers

from .models import Advertisement
from .models import ClientSession

class AdRecommendRequestSerializer(serializers.Serializer):
    """
    前端请求体：
    - latitude / longitude: 可选，用户不授权时为 null 或不传
    - user_agent: 必填
    - local_time: 可选，0-23 之间的整点小时，表示用户本地时间
    """

    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    user_agent = serializers.CharField(required=True, allow_blank=False)
    local_time = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=23,
        help_text="用户本地小时 (0-23)。如不传，由服务器时间决定。",
    )


class AdvertisementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Advertisement
        fields = [
            "id",
            "title",
            "image_url",
            "target_url",
            "click_count",
        ]


# 在文件底部增加：
class PortalAcceptResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientSession
        fields = ["ip_address", "is_authenticated", "first_seen", "last_seen"]

class PortalAcceptSerializer(serializers.Serializer):
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    accuracy_m = serializers.IntegerField(required=False, allow_null=True)


class PortalPingSerializer(serializers.Serializer):
    """
    前端心跳：
    - latitude/longitude: 无定位策略 A => 允许为 null
    - accuracy_m:
    - event: （ping/leave），leave 用于尽量在页面离开时收口
    """
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    accuracy_m = serializers.IntegerField(required=False, allow_null=True)
    event = serializers.ChoiceField(required=False, choices=["ping", "leave"], allow_null=True)
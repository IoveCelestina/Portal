# ads/models.py
from __future__ import annotations
from typing import Optional
from django.utils import timezone
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator


class DeviceOS(models.TextChoices):
    IOS = "ios", "iOS"
    ANDROID = "android", "Android"
    WINDOWS = "windows", "Windows"
    ALL = "all", "All"


class Advertisement(models.Model):
    """
    WIFI-Ad-Beacon 广告模型：
    - 支持按时间、设备类型、地理位置定向投放
    """

    # 基础信息
    title: str = models.CharField(max_length=255)
    image_url: str = models.URLField(max_length=500)
    target_url: str = models.URLField(max_length=500)
    click_count: int = models.PositiveIntegerField(default=0)

    # 是否启用
    is_active: bool = models.BooleanField(default=True)

    # 时间维度 (0-23 小时)
    # 规则：以“小时”为粒度，闭区间处理，支持跨天，如 18-2 表示 18:00 当天到次日 02:00。
    active_hour_start: int = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text="开始小时 (0-23)",
    )
    active_hour_end: int = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text="结束小时 (0-23)，若小于开始小时则表示跨天",
    )

    # 设备维度
    target_os: str = models.CharField(
        max_length=16,
        choices=DeviceOS.choices,
        default=DeviceOS.ALL,
        help_text="广告目标 OS：iOS / Android / Windows / All",
    )

    # 位置维度（简单版：使用经纬度 + 半径，Haversine 计算）
    target_lat: Optional[float] = models.FloatField(
        null=True, blank=True, help_text="目标纬度 (WGS84)"
    )
    target_lon: Optional[float] = models.FloatField(
        null=True, blank=True, help_text="目标经度 (WGS84)"
    )
    radius_meters: Optional[int] = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="有效半径（米）。为空表示不使用地理围栏（作为通用广告）",
    )

    # 通用广告 & 权重（兜底策略）
    is_generic: bool = models.BooleanField(
        default=False,
        help_text="是否为通用广告（位置失败或无匹配时的兜底广告）",
    )
    weight: float = models.FloatField(
        default=0.0,
        help_text="权重，兜底/通用广告时使用，值越大优先级越高",
    )

    # 审计字段
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ads_advertisement"  # 如果你原来就有就保留
        indexes = [
            # 1) 最常用过滤：是否投放中
            models.Index(fields=["is_active"]),

            # 2) 时间窗过滤（我们后续在 services.py 里会用 start/end 做候选生成）
            models.Index(fields=["active_hour_start", "active_hour_end"]),

            # 3) 设备过滤
            models.Index(fields=["target_os"]),

            # 4) 兜底/通用广告池
            models.Index(fields=["is_generic"]),

            # 5) 地理定向广告池：判断是否有 target_lat/target_lon/radius_meters
            # SQLite 不支持“部分索引条件”时，这里用普通索引先提升筛选速度
            models.Index(fields=["target_lat", "target_lon"]),
            models.Index(fields=["radius_meters"]),

            # 6) 排序常用字段（weight 越大越优先）
            models.Index(fields=["weight"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.target_os})"

    @property
    def has_location_target(self) -> bool:
        """是否配置了地理围栏"""
        return (
            self.target_lat is not None
            and self.target_lon is not None
            and self.radius_meters is not None
        )

class ClientSession(models.Model):
    ip_address = models.GenericIPAddressField()
    mac_address = models.CharField(max_length=32, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    is_authenticated = models.BooleanField(default=False)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    #位置
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    location_accuracy_m = models.IntegerField(blank=True, null=True)
    location_updated_at = models.DateTimeField(blank=True, null=True)

    # 关联到本地缓存的 POI
    venue = models.ForeignKey(
        "Venue",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="client_sessions",
    )

    # 匹配到该 POI 的距离（米）
    venue_distance_m = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = "ads_client_session"
        indexes = [
            models.Index(fields=["ip_address"]),
            models.Index(fields=["is_authenticated"]),
            models.Index(fields=["venue"]),
        ]

    def __str__(self) -> str:
        status = "AUTH" if self.is_authenticated else "PENDING"
        return f"{self.ip_address} ({status})"


class VenueCategory(models.TextChoices):
    SHOP = "SHOP", "商店"
    FOOD = "FOOD", "餐饮店"
    HOTEL = "HOTEL", "酒店"
    OTHER = "OTHER", "其他"


class Venue(models.Model):
    """
    预处理缓存的周边 POI（商店/餐饮/酒店等）。
    由管理命令定时拉取并写入，用于在线阶段快速匹配“用户在哪个地方”。
    """

    # 数据来源（后续支持多 provider）
    SOURCE_OVERPASS = "OVERPASS"
    SOURCE_AMAP = "AMAP"
    source = models.CharField(max_length=16, default=SOURCE_OVERPASS)

    # 外部 ID：例OSM 的 node/way/relation id/高德 POI id
    external_id = models.CharField(max_length=64)

    name = models.CharField(max_length=128)
    category = models.CharField(
        max_length=16,
        choices=VenueCategory.choices,
        default=VenueCategory.OTHER,
    )

    # 坐标
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    #补充信息（地址、标签等）
    address = models.CharField(max_length=255, blank=True, null=True)
    tags = models.JSONField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                name="uniq_venue_source_external_id",
            )
        ]
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.category})"



class VisitSource(models.TextChoices):
    GEOLOCATION = "GEO", "Geolocation"
    UNKNOWN = "UNK", "Unknown/No-Location"


class VisitSegment(models.Model):
    """
    一段停留：device 在某个 Venue（或未知）上的停留时间段。
    - venue 可为空：策略A（无定位/未命中）= Unknown
    - is_open=True 表示当前仍在持续的段（最后会被关闭）
    """

    device_key = models.CharField(max_length=32, db_index=True)  # 建议存 mac，小写带冒号，例如 "aa:bb:cc:dd:ee:ff"

    venue = models.ForeignKey(
        "Venue",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="visit_segments",
    )

    source = models.CharField(
        max_length=8,
        choices=VisitSource.choices,
        default=VisitSource.UNKNOWN,
    )

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    is_open = models.BooleanField(default=True)

    # 可选关联：方便从认证会话追溯（不强依赖）
    session = models.ForeignKey(
        "ClientSession",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="visit_segments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["device_key", "is_open"]),
            models.Index(fields=["device_key", "start_at"]),
            models.Index(fields=["venue", "start_at"]),
        ]

    def __str__(self) -> str:
        v = self.venue.name if self.venue else "UNKNOWN"
        return f"{self.device_key} -> {v} [{self.start_at} ~ {self.end_at}]"


class DeviceVisitState(models.Model):
    """
    设备停留状态机的持久化状态（用于 1 分钟采样下的“抖动保护”）。

    规则（后续在 services.py 实现）：
    - 若新 venue 与当前 venue 不同，不立刻切段
    - 需要新 venue 连续命中 N 次（建议 N=2）才切段
    - pending_* 用于保存候选 venue 以及命中次数
    """

    device_key = models.CharField(max_length=32, unique=True)

    current_segment = models.ForeignKey(
        "VisitSegment",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="current_for_devices",
    )
    current_venue = models.ForeignKey(
        "Venue",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="current_for_devices",
    )

    pending_venue = models.ForeignKey(
        "Venue",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="pending_for_devices",
    )
    pending_count = models.IntegerField(default=0)

    last_ping_at = models.DateTimeField(blank=True, null=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["device_key"]),
            models.Index(fields=["last_ping_at"]),
        ]

    def __str__(self) -> str:
        cur = self.current_venue.name if self.current_venue else "UNKNOWN"
        pen = self.pending_venue.name if self.pending_venue else "NONE"
        return f"{self.device_key}: current={cur}, pending={pen}({self.pending_count})"
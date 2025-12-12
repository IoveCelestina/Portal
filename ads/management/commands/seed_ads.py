# ads/management/commands/seed_ads.py
from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from ads.models import Advertisement, DeviceOS


class Command(BaseCommand):
    help = "Seed initial advertisements for WIFI-Ad-Beacon MVP."

    def handle(self, *args: Any, **options: Any) -> None:
        # 为了方便，你 Postman 里用的是上海市中心的大致坐标
        shanghai_lat = 31.2304
        shanghai_lon = 121.4737

        ads_data = [
            # 1) 早餐广告：早上 6-10 点，所有 OS，位置限制 800m 内
            dict(
                title="城市商圈早餐优惠",
                image_url="https://www.huawei.com/-/media/hcomponent-header/1.0.1.20251208095539/component/img/huawei_logo.png",
                target_url="https://www.huawei.com/cn/",
                click_count=0,
                is_active=True,
                active_hour_start=6,
                active_hour_end=10,
                target_os=DeviceOS.ALL,
                target_lat=shanghai_lat,
                target_lon=shanghai_lon,
                radius_meters=800,
                is_generic=False,
                weight=5.0,
            ),
            # 2) 咖啡券：9-18 点，仅 iOS，500m 内
            dict(
                title="星巴克附近咖啡买一送一",
                image_url="https://www.huawei.com/-/media/hcomponent-header/1.0.1.20251208095539/component/img/huawei_logo.png",
                target_url="https://www.huawei.com/cn/",
                click_count=0,
                is_active=True,
                active_hour_start=9,
                active_hour_end=18,
                target_os=DeviceOS.IOS,
                target_lat=shanghai_lat,
                target_lon=shanghai_lon,
                radius_meters=500,
                is_generic=False,
                weight=10.0,
            ),
            # 3) 夜宵：18-2 点跨天，所有 OS，1.5km 内
            dict(
                title="深夜烧烤啤酒畅饮",
                image_url="https://www.huawei.com/-/media/hcomponent-header/1.0.1.20251208095539/component/img/huawei_logo.png",
                target_url="https://www.huawei.com/cn/",
                click_count=0,
                is_active=True,
                active_hour_start=18,
                active_hour_end=2,  # 跨天：18:00 到次日 2:00
                target_os=DeviceOS.ALL,
                target_lat=shanghai_lat,
                target_lon=shanghai_lon,
                radius_meters=1500,
                is_generic=False,
                weight=7.0,
            ),
            # 4) 通用广告：全天、所有 OS、无位置限制（兜底）
            dict(
                title="WIFI-Ad-Beacon 通用品牌曝光",
                image_url="https://www.huawei.com/-/media/hcomponent-header/1.0.1.20251208095539/component/img/huawei_logo.png",
                target_url="https://www.huawei.com/cn/",
                click_count=0,
                is_active=True,
                active_hour_start=0,
                active_hour_end=23,
                target_os=DeviceOS.ALL,
                target_lat=None,
                target_lon=None,
                radius_meters=None,
                is_generic=False, #先关掉兜底
                weight=100.0,  # 兜底优先级最高
            ),
        ]

        created_count = 0
        updated_count = 0

        for data in ads_data:
            ad, created = Advertisement.objects.update_or_create(
                title=data["title"],
                defaults=data,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seed finished. Created {created_count}, Updated {updated_count} advertisements."
        ))


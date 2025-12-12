from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ads.models import Venue, VenueCategory


@dataclass(frozen=True)
class PoiItem:
    external_id: str
    name: str
    category: str
    latitude: float
    longitude: float
    address: Optional[str]
    tags: Dict[str, Any]


FOOD_AMENITIES = {"restaurant", "cafe", "fast_food", "bar", "pub"}
HOTEL_TOURISM = {"hotel", "hostel", "motel", "guest_house"}


def _get_float_setting(name: str) -> float:
    v = getattr(settings, name, None)
    if v is None:
        raise CommandError(f"Missing setting: {name}")
    return float(v)


def _get_int_setting(name: str) -> int:
    v = getattr(settings, name, None)
    if v is None:
        raise CommandError(f"Missing setting: {name}")
    return int(v)


def _http_post_json(url: str, payload: str, timeout: int) -> Dict[str, Any]:
    """
    Minimal HTTP client using stdlib (no extra dependencies).
    Overpass expects POST body "data=<query>" or raw query; we use raw query body.
    """
    data = payload.encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "WIFI-Ad-Beacon/1.0 (POI preload)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)


def _build_overpass_query(lat: float, lon: float, radius_m: int, timeout_s: int) -> str:
    """
    Overpass QL:
    - 拉取 node/way/relation
    - shop=* 归类为 SHOP
    - amenity=restaurant/cafe/fast_food/bar/pub 归类为 FOOD
    - tourism=hotel/hostel/motel/guest_house 归类为 HOTEL
    """
    # out center: way/relation 使用 center 字段
    q = f"""
[out:json][timeout:{timeout_s}];
(
  node(around:{radius_m},{lat},{lon})[amenity~"^(restaurant|cafe|fast_food|bar|pub)$"];
  way(around:{radius_m},{lat},{lon})[amenity~"^(restaurant|cafe|fast_food|bar|pub)$"];
  relation(around:{radius_m},{lat},{lon})[amenity~"^(restaurant|cafe|fast_food|bar|pub)$"];

  node(around:{radius_m},{lat},{lon})[shop];
  way(around:{radius_m},{lat},{lon})[shop];
  relation(around:{radius_m},{lat},{lon})[shop];

  node(around:{radius_m},{lat},{lon})[tourism~"^(hotel|hostel|motel|guest_house)$"];
  way(around:{radius_m},{lat},{lon})[tourism~"^(hotel|hostel|motel|guest_house)$"];
  relation(around:{radius_m},{lat},{lon})[tourism~"^(hotel|hostel|motel|guest_house)$"];
);
out tags center;
"""
    # Overpass 常用形式：POST body 为 data=<urlencoded query>
    return "data=" + urllib.parse.quote(q.strip())


def _infer_category(tags: Dict[str, Any]) -> str:
    shop = tags.get("shop")
    amenity = tags.get("amenity")
    tourism = tags.get("tourism")

    if shop:
        return VenueCategory.SHOP
    if amenity and str(amenity) in FOOD_AMENITIES:
        return VenueCategory.FOOD
    if tourism and str(tourism) in HOTEL_TOURISM:
        return VenueCategory.HOTEL
    return VenueCategory.OTHER


def _parse_overpass_elements(elements: List[Dict[str, Any]]) -> List[PoiItem]:
    items: List[PoiItem] = []

    for el in elements:
        el_type = el.get("type")
        el_id = el.get("id")
        if not el_type or el_id is None:
            continue

        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            # 没有 name 的 POI 价值较低，但仍可保留（用类型+id 兜底）
            name = f"{el_type}:{el_id}"

        # 坐标：node 直接 lat/lon；way/relation 用 center
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            center = el.get("center") or {}
            lat = center.get("lat")
            lon = center.get("lon")
        if lat is None or lon is None:
            continue

        category = _infer_category(tags)

        # 简单拼地址：可按需增强
        address_parts = []
        for k in ("addr:city", "addr:district", "addr:street", "addr:housenumber"):
            if tags.get(k):
                address_parts.append(str(tags.get(k)))
        address = " ".join(address_parts) if address_parts else None

        external_id = f"{el_type}/{el_id}"

        items.append(
            PoiItem(
                external_id=external_id,
                name=name,
                category=category,
                latitude=float(lat),
                longitude=float(lon),
                address=address,
                tags=tags,
            )
        )

    return items


def _fetch_overpass_pois() -> List[PoiItem]:
    lat = _get_float_setting("PORTAL_SITE_LATITUDE")
    lon = _get_float_setting("PORTAL_SITE_LONGITUDE")
    radius_m = _get_int_setting("PORTAL_POI_PRELOAD_RADIUS_M")
    endpoint = getattr(settings, "PORTAL_OVERPASS_ENDPOINT", "https://overpass-api.de/api/interpreter")
    timeout_s = int(getattr(settings, "PORTAL_OVERPASS_TIMEOUT_SEC", 25))

    query = _build_overpass_query(lat=lat, lon=lon, radius_m=radius_m, timeout_s=timeout_s)
    data = _http_post_json(url=endpoint, payload=query, timeout=timeout_s)

    elements = data.get("elements") or []
    if not isinstance(elements, list):
        return []
    return _parse_overpass_elements(elements)


class Command(BaseCommand):
    help = "Preload nearby POIs into local Venue cache (Scheme 1: offline/periodic cache)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--provider",
            type=str,
            default=getattr(settings, "PORTAL_POI_PROVIDER", "OVERPASS"),
            help='POI provider: "OVERPASS" (default) or "AMAP".',
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete existing venues for this provider before importing.",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            default=bool(getattr(settings, "PORTAL_POI_DEACTIVATE_MISSING", True)),
            help="Mark venues not returned in this run as inactive (default from settings).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        provider = str(options["provider"]).upper().strip()
        purge = bool(options["purge"])
        deactivate_missing = bool(options["deactivate_missing"])

        if provider not in {"OVERPASS", "AMAP"}:
            raise CommandError('provider must be "OVERPASS" or "AMAP"')

        if provider == "AMAP":
            raise CommandError('AMAP provider not implemented yet in this command. Use provider="OVERPASS" for now.')

        source = Venue.SOURCE_OVERPASS

        if purge:
            deleted, _ = Venue.objects.filter(source=source).delete()
            self.stdout.write(self.style.WARNING(f"Purged {deleted} Venue rows for source={source}"))

        self.stdout.write(f"Fetching POIs via provider={provider} ...")
        pois = _fetch_overpass_pois()
        self.stdout.write(f"Fetched {len(pois)} POIs")

        seen_ids: Set[str] = set()
        created = 0
        updated = 0

        for p in pois:
            seen_ids.add(p.external_id)
            obj, was_created = Venue.objects.update_or_create(
                source=source,
                external_id=p.external_id,
                defaults={
                    "name": p.name,
                    "category": p.category,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "address": p.address,
                    "tags": p.tags,
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        deactivated = 0
        if deactivate_missing:
            qs = Venue.objects.filter(source=source, is_active=True).exclude(external_id__in=seen_ids)
            deactivated = qs.update(is_active=False)

        self.stdout.write(
            self.style.SUCCESS(
                f"POI preload done. created={created}, updated={updated}, deactivated={deactivated}"
            )
        )


'''
先清空再导入：python manage.py preload_poi --purge
不停用缺失：python manage.py preload_poi --deactivate-missing=0
'''
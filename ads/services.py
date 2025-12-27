from __future__ import annotations
from typing import Tuple
import math,os,re,subprocess
from typing import Iterable, Optional
from django.db.models import Q, F
from django.utils import timezone
from ads.models import ClientSession, Venue, VisitSegment, VisitSource, DeviceVisitState
from .models import Advertisement, DeviceOS
from subprocess import CalledProcessError, run
from django.conf import settings
import hashlib
from django.core.cache import cache

import logging
logger = logging.getLogger(__name__)

def detect_os_from_user_agent(user_agent: str) -> DeviceOS:
    """
    简单的 UA 解析，适合 MVP。
    real项目可替换为 ua-parser 等库。
    """
    ua = user_agent.lower()

    if "iphone" in ua or "ipad" in ua or "ipod" in ua or "ios" in ua:
        return DeviceOS.IOS
    if "android" in ua:
        return DeviceOS.ANDROID
    if "windows" in ua:
        return DeviceOS.WINDOWS
    return DeviceOS.ALL  # 或者作为 OTHER，MVP 用 ALL 兼容通用广告


def haversine_distance_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    使用 Haversine 公式计算两点距离（单位：米）
    输入：纬度/经度，单位：度 (WGS84)
    """
    radius_earth_m = 6371000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_earth_m * c


def is_hour_in_range(
    current_hour: int,
    start_hour: int,
    end_hour: int,
) -> bool:
    """
    判断当前小时是否在广告配置的时间范围内。
    支持跨天配置：
      - start <= end: 直接区间 [start, end]
      - start > end : 表示跨天，例如 18-2 -> [18-23] U [0-2]
    """
    if start_hour == end_hour:
        # 特殊情况：相等时理解为“全天”
        return True

    if start_hour < end_hour:
        return start_hour <= current_hour <= end_hour
    # 跨天
    return current_hour >= start_hour or current_hour <= end_hour


def build_time_q(current_hour: int) -> Q:
    h = int(current_hour)

    # 1) start == end 视为全天
    q_all_day = Q(active_hour_start=F("active_hour_end"))

    # 2) start < end ：start <= h <= end
    q_same_day = Q(active_hour_start__lt=F("active_hour_end")) & Q(
        active_hour_start__lte=h,
        active_hour_end__gte=h,
    )

    # 3) start > end ：跨天：h>=start 或 h<=end
    q_cross_day = Q(active_hour_start__gt=F("active_hour_end")) & (
        Q(active_hour_start__lte=h) | Q(active_hour_end__gte=h)
    )

    return q_all_day | q_same_day | q_cross_day






def recommend_advertisement_v2(
    *,
    latitude: Optional[float],
    longitude: Optional[float],
    user_agent: str,
    local_hour: Optional[int] = None,
) -> Optional[Advertisement]:
    """
    根据 [时间、设备类型、位置] 推荐一个最匹配的广告。

    隐私说明：
    - 本函数仅在内存中使用 latitude/longitude 进行距离计算。
    - 不会将用户坐标写入任何持久化存储（DB / 日志）。
    - 如需日志，可考虑只记录粗粒度信息（如城市级别或 hash 后坐标）。
    """

    # 1) 解析 OS
    device_os = detect_os_from_user_agent(user_agent=user_agent)

    # 2) 获取当前小时（0-23），优先使用调用方的 local_hour
    if local_hour is not None:
        current_hour = local_hour
    else:
        current_hour = timezone.localtime().hour

    # 3) 初步筛选：只取 is_active=True 的广告
    qs = Advertisement.objects.filter(is_active=True)

    # 4) 逐条在 Python 内存中做「时间 + 设备」过滤
    time_device_matched_ads: list[Advertisement] = []
    for ad in qs:
        # 时间过滤
        if not is_hour_in_range(
            current_hour=current_hour,
            start_hour=ad.active_hour_start,
            end_hour=ad.active_hour_end,
        ):
            continue

        # 设备过滤
        if ad.target_os != DeviceOS.ALL and ad.target_os != device_os:
            continue

        time_device_matched_ads.append(ad)

    # 没有任何满足时间+设备的广告，直接返回 None（也可以再放宽规则）
    if not time_device_matched_ads:
        return None

    # 5) 如果有位置，先尝试从“有地理围栏”的广告中找最近的
    location_matched: list[Tuple[Advertisement, float]] = []

    if latitude is not None and longitude is not None:
        for ad in time_device_matched_ads:
            if not ad.has_location_target:
                continue

            distance = haversine_distance_meters(
                latitude,
                longitude,
                ad.target_lat,  # type: ignore[arg-type]
                ad.target_lon,  # type: ignore[arg-type]
            )

            if ad.radius_meters is not None and distance <= ad.radius_meters:
                location_matched.append((ad, distance))

    # 6) 优先返回最近的地理匹配广告
    if location_matched:
        # 按距离升序，若相同距离则按 weight 降序
        location_matched.sort(
            key=lambda item: (item[1], -item[0].weight),
        )
        return location_matched[0][0]

    # 7) 位置为空或没有地理匹配，则走兜底策略：通用广告
    generic_ads: list[Advertisement] = [
        ad for ad in time_device_matched_ads if ad.is_generic
    ]

    if generic_ads:
        # 权重最高的通用广告（weight 越大优先级越高）
        generic_ads.sort(key=lambda ad: ad.weight, reverse=True)
        return generic_ads[0]

    # 8) 实在没有通用广告，则在 time_device_matched_ads 中选一个权重最高的
    time_device_matched_ads.sort(key=lambda ad: ad.weight, reverse=True)
    return time_device_matched_ads[0] if time_device_matched_ads else None




def get_client_ip_from_request(request) -> str:
    """
    简单获取客户端 IP。
    - 若有反向代理，可先看 X-Forwarded-For 等，这里 MVP 直接用 REMOTE_ADDR。
    """
    meta = request.META
    ip = meta.get("HTTP_X_FORWARDED_FOR")
    if ip:
        # 可能是 "client, proxy1, proxy2" 这种格式
        ip = ip.split(",")[0].strip()
        return ip
    return meta.get("REMOTE_ADDR", "")



def mark_client_authenticated(
    ip_address: str,
    user_agent: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> ClientSession:
    """
    标记客户端通过 Portal 认证：
    - 必须：IP、user_agent
    - 可选：latitude / longitude，用于绑定最近的 venue（如果你有这套逻辑）
    - 在 Windows 开发环境不会执行任何 iptables/ipset 脚本
    """
    session, _ = ClientSession.objects.get_or_create(
        ip_address=ip_address,
        defaults={"user_agent": user_agent or ""},
    )

    session.is_authenticated = True
    session.user_agent = user_agent or session.user_agent

    # ⭐ 只有在有坐标时才尝试匹配最近场馆
    if latitude is not None and longitude is not None:
        try:
            venue, distance_m = match_nearest_venue(
                latitude=latitude,
                longitude=longitude,
            )
            # 如果你在 ClientSession 上有这些字段，就在这里赋值：
            # session.venue = venue
            # session.distance_to_venue_m = distance_m
        except Exception as exc:
            # 不要让匹配失败影响认证本身
            logger.warning(
                "match_nearest_venue failed for %s (lat=%s, lon=%s): %s",
                ip_address,
                latitude,
                longitude,
                exc,
            )

    # 保存基本认证信息（如果上面多加了字段，记得一起写进 update_fields）
    session.save(update_fields=["is_authenticated", "user_agent", "last_seen"])

    # ⭐ 放行脚本：仅当设置了路径且文件存在时才执行（Windows 下通常不会执行）
    allow_script = getattr(settings, "PORTAL_ALLOW_IP_SCRIPT", None)
    if allow_script and os.path.isfile(allow_script):
        try:
            run([allow_script, ip_address], check=True)
        except (CalledProcessError, FileNotFoundError) as exc:
            logger.error("Failed to run allow script for %s: %s", ip_address, exc)

    return session
#ip->mac解析函数
_MAC_RE = re.compile(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")

def _mac_from_dnsmasq_leases(ip: str) -> str | None:
    leases_path = getattr(settings, "PORTAL_DHCP_LEASES_FILE", "/var/lib/misc/dnsmasq.leases")
    if not os.path.exists(leases_path):
        return None
    # dnsmasq.leases: <expiry> <mac> <ip> <hostname> <clientid>
    try:
        with open(leases_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[2] == ip and _MAC_RE.fullmatch(parts[1]):
                    return parts[1].lower()
    except Exception:
        return None
    return None

def _mac_from_ip_neigh(ip: str) -> str | None:
    # 需要内核邻居表里已有条目；如果没有，可能需要先有过通信/ARP
    try:
        out = subprocess.check_output(["ip", "neigh", "show", "to", ip], text=True, stderr=subprocess.DEVNULL)
        m = _MAC_RE.search(out)
        return m.group(0).lower() if m else None
    except Exception:
        return None

def resolve_mac_address(ip: str) -> str | None:
    mac = _mac_from_dnsmasq_leases(ip)
    if mac:
        return mac
    return _mac_from_ip_neigh(ip)



# ====== POI / Venue 在线匹配（预处理缓存 + 在线本地匹配） ======

def _meters_to_lat_delta(meters: float) -> float:
    # 1 纬度度数约 111,111m
    return meters / 111111.0


def _meters_to_lon_delta(meters: float, at_lat: float) -> float:
    # 经度随纬度变化：meters / (111111 * cos(lat))
    denom = 111111.0 * max(math.cos(math.radians(at_lat)), 1e-6)
    return meters / denom


def match_nearest_venue(
    *,
    latitude: float,
    longitude: float,
) -> tuple[Venue | None, float | None]:
    """
    在本地 Venue 缓存中匹配用户坐标附近最近的 POI。
    返回：(venue, distance_m)。若无命中则 (None, None)。

    命中条件：distance <= settings.PORTAL_POI_MATCH_MAX_DISTANCE_M
    """
    max_m = int(getattr(settings, "PORTAL_POI_MATCH_MAX_DISTANCE_M", 120))
    if max_m <= 0:
        return None, None

    # 先做一个粗过滤（经纬度 bounding box），减少 Python 里算距离的数量
    lat_delta = _meters_to_lat_delta(max_m)
    lon_delta = _meters_to_lon_delta(max_m, at_lat=latitude)

    qs = (
        Venue.objects.filter(is_active=True)
        .filter(
            latitude__gte=latitude - lat_delta,
            latitude__lte=latitude + lat_delta,
            longitude__gte=longitude - lon_delta,
            longitude__lte=longitude + lon_delta,
        )
        .only("id", "name", "category", "latitude", "longitude", "source", "external_id")
    )

    best: Venue | None = None
    best_d: float | None = None

    for v in qs:
        d = haversine_distance_meters(
            latitude,
            longitude,
            float(v.latitude),
            float(v.longitude),
        )
        if d <= max_m and (best_d is None or d < best_d):
            best = v
            best_d = d

    return best, best_d


def _apply_matched_venue_to_session(session: ClientSession, venue: Venue, distance_m: float | None) -> None:
    """
    仅存 venue 外键 + 距离快照。
    """
    session.venue = venue
    session.venue_distance_m = int(distance_m) if distance_m is not None else None

# ====== Visit Segments：多店铺停留分段（1分钟采样）======

def _get_device_key_from_ip(ip_address: str) -> str:
    """
    优先用 MAC 作为 device_key；解析不到就用 ip:* 兜底。
    device_key 字段长度为 32，MAC(ipv4) 都够用。
    """
    mac = resolve_mac_address(ip_address)
    if mac:
        return mac.lower()
    return f"ip:{ip_address}"


def _get_or_create_session(ip_address: str, user_agent: str | None) -> ClientSession:
    session, _ = ClientSession.objects.get_or_create(ip_address=ip_address)
    if user_agent:
        session.user_agent = user_agent
    # 更新 last_seen（auto_now=True 会在 save 时更新）
    session.save()
    return session


def _close_open_segment(seg: VisitSegment, end_at) -> None:
    seg.end_at = end_at
    seg.is_open = False
    seg.save(update_fields=["end_at", "is_open", "updated_at"])


def _extend_open_segment(seg: VisitSegment, now) -> None:
    seg.end_at = now
    seg.save(update_fields=["end_at", "updated_at"])


def _create_open_segment(
    *,
    device_key: str,
    venue: Venue | None,
    source: str,
    now,
    session: ClientSession | None,
) -> VisitSegment:
    return VisitSegment.objects.create(
        device_key=device_key,
        venue=venue,
        source=source,
        start_at=now,
        end_at=now,
        is_open=True,
        session=session,
    )


def upsert_visit_segment(
    *,
    ip_address: str,
    user_agent: str | None,
    latitude: float | None,
    longitude: float | None,
    accuracy_m: int | None = None,
    event: str | None = None,  # "ping" | "leave" | None
) -> dict:
    """
    心跳驱动的“多店铺停留分段”状态机（策略A：无定位 => venue=None）。

    关键规则：
    - 采样周期：你前端 60 秒一次
    - 抖动保护：新 venue 连续命中 N 次才切段（默认 N=2）
    - 超时闭段：超过 inactivity_timeout 秒未 ping，自动结束上一段并重置状态
    - event=leave：立即收口当前段并重置状态
    """
    now = timezone.now()

    # 参数（可在 settings.py 配置）
    switch_confirmations = int(getattr(settings, "PORTAL_VISIT_SWITCH_CONFIRMATIONS", 2))
    inactivity_timeout_sec = int(getattr(settings, "PORTAL_VISIT_INACTIVITY_TIMEOUT_SEC", 150))

    # 1) device_key（优先 MAC）
    device_key = _get_device_key_from_ip(ip_address)

    # 2) 关联/刷新 session（可选，但建议）
    session = _get_or_create_session(ip_address=ip_address, user_agent=user_agent)

    # 3) 根据定位匹配 Venue（策略A：没有定位 => venue=None）
    matched_venue: Venue | None = None
    matched_distance_m: float | None = None
    source = VisitSource.UNKNOWN

    if latitude is not None and longitude is not None:
        # 你已有方案1：本地 Venue 缓存匹配
        v, d = match_nearest_venue(latitude=latitude, longitude=longitude)
        matched_venue = v
        matched_distance_m = d
        source = VisitSource.GEOLOCATION
    else:
        matched_venue = None
        matched_distance_m = None
        source = VisitSource.UNKNOWN

    # 可选：把定位写回 session（你若希望留存位置）
    if latitude is not None and longitude is not None:
        session.latitude = latitude
        session.longitude = longitude
        session.location_accuracy_m = accuracy_m
        session.location_updated_at = now
        session.save()

    # 4) 载入状态机状态
    state, _ = DeviceVisitState.objects.get_or_create(device_key=device_key)

    # 5) 超时闭段：长时间没 ping，结束旧段并重置
    if state.last_ping_at is not None:
        delta = (now - state.last_ping_at).total_seconds()
        if delta > inactivity_timeout_sec:
            if state.current_segment and state.current_segment.is_open:
                # 用 last_ping_at 收口更保守，不夸大停留时长
                _close_open_segment(state.current_segment, end_at=state.last_ping_at)

            state.current_segment = None
            state.current_venue = None
            state.pending_venue = None
            state.pending_count = 0

    # 6) event=leave：立即收口并重置
    if event == "leave":
        if state.current_segment and state.current_segment.is_open:
            _close_open_segment(state.current_segment, end_at=now)

        state.current_segment = None
        state.current_venue = None
        state.pending_venue = None
        state.pending_count = 0
        state.last_ping_at = now
        state.save()
        return {
            "ok": True,
            "device_key": device_key,
            "event": "leave",
            "venue": None,
            "distance_m": None,
        }

    target_venue = matched_venue  # 可能为 None（未知）

    # 7) 没有当前段：直接开段
    if state.current_segment is None or not state.current_segment.is_open:
        seg = _create_open_segment(
            device_key=device_key,
            venue=target_venue,
            source=source,
            now=now,
            session=session,
        )
        state.current_segment = seg
        state.current_venue = target_venue
        state.pending_venue = None
        state.pending_count = 0
        state.last_ping_at = now
        state.save()

        return {
            "ok": True,
            "device_key": device_key,
            "venue": (target_venue.name if target_venue else None),
            "venue_id": (target_venue.id if target_venue else None),
            "distance_m": int(matched_distance_m) if matched_distance_m is not None else None,
            "segment_id": seg.id,
        }

    # 8) 有当前段：决定延长还是切段
    cur_venue = state.current_venue  # 可能 None

    same_venue = (
        (cur_venue is None and target_venue is None)
        or (cur_venue is not None and target_venue is not None and cur_venue.id == target_venue.id)
    )

    if same_venue:
        # 延长当前段
        _extend_open_segment(state.current_segment, now=now)

        # 清空 pending（恢复稳定）
        state.pending_venue = None
        state.pending_count = 0
        state.last_ping_at = now
        state.save()

        return {
            "ok": True,
            "device_key": device_key,
            "venue": (cur_venue.name if cur_venue else None),
            "venue_id": (cur_venue.id if cur_venue else None),
            "distance_m": int(matched_distance_m) if matched_distance_m is not None else None,
            "segment_id": state.current_segment.id,
        }

    # 9) venue 不同：进入“连续命中确认”逻辑（抖动保护）
    pending_same = (
        (state.pending_venue is None and target_venue is None)
        or (state.pending_venue is not None and target_venue is not None and state.pending_venue.id == target_venue.id)
    )

    # 无论 pending 是否确认，我们在确认前仍然延长当前段（认为仍在当前店）
    _extend_open_segment(state.current_segment, now=now)

    if pending_same:
        state.pending_count += 1
    else:
        state.pending_venue = target_venue
        state.pending_count = 1

    # 确认次数足够：真正切段
    if state.pending_count >= max(switch_confirmations, 1):
        # 关闭旧段（用 now 收口）
        _close_open_segment(state.current_segment, end_at=now)

        # 开新段
        new_seg = _create_open_segment(
            device_key=device_key,
            venue=target_venue,
            source=source,
            now=now,
            session=session,
        )

        state.current_segment = new_seg
        state.current_venue = target_venue
        state.pending_venue = None
        state.pending_count = 0
        state.last_ping_at = now
        state.save()

        return {
            "ok": True,
            "device_key": device_key,
            "venue": (target_venue.name if target_venue else None),
            "venue_id": (target_venue.id if target_venue else None),
            "distance_m": int(matched_distance_m) if matched_distance_m is not None else None,
            "segment_id": new_seg.id,
            "switched": True,
        }

    # 未达到确认次数：保持当前段，记录 pending
    state.last_ping_at = now
    state.save()

    return {
        "ok": True,
        "device_key": device_key,
        "venue": (cur_venue.name if cur_venue else None),
        "venue_id": (cur_venue.id if cur_venue else None),
        "distance_m": int(matched_distance_m) if matched_distance_m is not None else None,
        "segment_id": state.current_segment.id,
        "pending_venue": (target_venue.name if target_venue else None),
        "pending_count": state.pending_count,
        "switched": False,
    }



def recommend_advertisement_v2(
    *,
    latitude: Optional[float],
    longitude: Optional[float],
    user_agent: str,
    local_hour: Optional[int] = None,
    client_ip: str | None = None,  # 新增：用于频控 key
) -> Optional[Advertisement]:

    """
    v2 推荐：DB 过滤生成候选集 + Python 只算少量距离。

    规则优先级：
    1) 若有定位：优先在“地理命中”的广告里选（距离/权重综合）
    2) 否则或无地理命中：从“通用/无地理要求”候选里选（按 weight）
    """

    device_os = detect_os_from_user_agent(user_agent=user_agent)
    current_hour = int(local_hour) if local_hour is not None else timezone.localtime().hour

    # 时间 + OS + active 基础候选（尽量下推 DB）
    time_q = build_time_q(current_hour)
    os_q = Q(target_os=DeviceOS.ALL) | Q(target_os=device_os)

    base_qs = (
        Advertisement.objects.filter(is_active=True)
        .filter(time_q)
        .filter(os_q)
        .only(
            "id",
            "title",
            "image_url",
            "target_url",
            "click_count",
            "weight",
            "is_generic",
            "target_lat",
            "target_lon",
            "radius_meters",
            "active_hour_start",
            "active_hour_end",
            "target_os",
        )
    )

    # ===== 频控（最小版）=====
    freq_ttl_sec = int(getattr(settings, "AD_FREQCAP_TTL_SEC", 600))       # 默认 10 分钟
    freq_max_recent = int(getattr(settings, "AD_FREQCAP_MAX_RECENT", 3))   # 默认最近 3 条不重复
    freq_key = _freqcap_key(client_ip, user_agent)
    recent_ids = _freqcap_get_recent_ids(freq_key)

    # 地理定向广告（有围栏）
    location_target_q = Q(target_lat__isnull=False) & Q(target_lon__isnull=False) & Q(radius_meters__isnull=False)

    # 通用/不依赖定位广告：is_generic=True 或没有围栏配置
    generic_q = Q(is_generic=True) | ~location_target_q

    # 1) 有定位：先尝试地理命中
    if latitude is not None and longitude is not None:
        # 先用 bbox 粗过滤：只取用户附近“可能命中”的围栏广告，再算精确距离
        max_r = 2000  # 先写死一个上限（米）
        lat_delta = max_r / 111111.0
        lon_delta = max_r / (111111.0 * max(math.cos(math.radians(latitude)), 1e-6))

        loc_candidates = list(
            _exclude_recent(base_qs.filter(location_target_q), recent_ids)
            .filter(
                target_lat__gte=latitude - lat_delta,
                target_lat__lte=latitude + lat_delta,
                target_lon__gte=longitude - lon_delta,
                target_lon__lte=longitude + lon_delta,
            )
            .order_by("-weight")[:1000]
        )

        if not loc_candidates and recent_ids:
            loc_candidates = list(
                base_qs.filter(location_target_q)
                .filter(
                    target_lat__gte=latitude - lat_delta,
                    target_lat__lte=latitude + lat_delta,
                    target_lon__gte=longitude - lon_delta,
                    target_lon__lte=longitude + lon_delta,
                )
                .order_by("-weight")[:1000]
            )


        best_ad: Optional[Advertisement] = None
        best_score: float = -1e18

        geo_hits = 0
        for ad in loc_candidates:
            # 防御：字段可能为 None
            if ad.target_lat is None or ad.target_lon is None or ad.radius_meters is None:
                continue

            d = haversine_distance_meters(
                latitude,
                longitude,
                float(ad.target_lat),
                float(ad.target_lon),
            )
            if d > float(ad.radius_meters):
                continue
            geo_hits += 1

            # 综合评分：weight 为主，距离为辅（越近越好）
            # 你可以后续调参：w_weight / w_dist
            w_weight = 10.0
            w_dist = 5.0

            # 距离分：0m -> 1.0, 距离=radius -> 0.0
            dist_norm = max(0.0, 1.0 - (d / float(ad.radius_meters)))
            score = (float(ad.weight) * w_weight) + (dist_norm * w_dist)

            if score > best_score:
                best_score = score
                best_ad = ad

        print("ad-v2 geo candidates:", len(loc_candidates), "geo hits:", geo_hits, "best:",
              getattr(best_ad, "id", None))
        if best_ad is not None:
            _freqcap_record(freq_key, best_ad.id, ttl_sec=freq_ttl_sec, max_recent=freq_max_recent)
            return best_ad

    # 2) 没定位或无地理命中：走通用/无围栏广告池
    # 同样避免一次性取太多：按 weight 截断
    generic_candidates = list(_exclude_recent(base_qs.filter(generic_q), recent_ids).order_by("-weight")[:200])
    if not generic_candidates and recent_ids:
        generic_candidates = list(base_qs.filter(generic_q).order_by("-weight")[:200])

    if not generic_candidates:
        return None

    chosen = generic_candidates[0]
    _freqcap_record(freq_key, chosen.id, ttl_sec=freq_ttl_sec, max_recent=freq_max_recent)
    return chosen


def _freqcap_key(client_ip: str | None, user_agent: str) -> str:
    """
    频控 key：优先用 IP（后续你也可以换成 MAC 或 device_key），UA 做兜底区分。
    """
    base = (client_ip or "noip") + "|" + (user_agent or "noua")
    h = hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
    return f"ad:freq:{h}"

def _freqcap_get_recent_ids(key: str) -> list[int]:
    val = cache.get(key)
    if isinstance(val, list):
        # 只保留 int
        return [int(x) for x in val if str(x).isdigit()]
    return []

def _freqcap_record(key: str, ad_id: int, *, ttl_sec: int, max_recent: int) -> None:
    """
    记录最近展示广告：去重 + 截断 + TTL。
    """
    recent = _freqcap_get_recent_ids(key)
    # 去掉已存在的 ad_id，再插入到最前
    recent = [x for x in recent if x != int(ad_id)]
    recent.insert(0, int(ad_id))
    recent = recent[:max_recent]
    cache.set(key, recent, timeout=ttl_sec)

def _exclude_recent(qs, recent_ids: list[int]):
    if not recent_ids:
        return qs
    return qs.exclude(id__in=recent_ids)

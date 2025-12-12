// frontend/portal.ts

// 通用 DOM 查询工具
function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) {
    throw new Error(`Element with id "${id}" not found`);
  }
  return el;
}

interface Ad {
  id: number;
  title: string;
  image_url: string;
  target_url: string;
  click_count: number;
}

interface AdApiPayload {
  latitude: number | null;
  longitude: number | null;
  user_agent: string;
  local_time: number;
}

function setStatus(text: string): void {
  const statusEl = $("status");
  statusEl.textContent = text;
}
function setAcceptStatus(text: string): void {
  const el = $("accept-status");
  el.textContent = text;
}


async function requestAd(
  latitude: number | null,
  longitude: number | null
): Promise<void> {
  const adCardEl = $("ad-card");
  const adTitleEl = $("ad-title");
  const adImageEl = $("ad-image") as HTMLImageElement;
  const adLinkEl = $("ad-link") as HTMLAnchorElement;
  const emptyEl = $("empty");
  const errorEl = $("error");

  const payload: AdApiPayload = {
    latitude,
    longitude,
    user_agent: navigator.userAgent,
    local_time: new Date().getHours(),
  };

  setStatus("正在获取推荐广告...");

  try {
    const response = await fetch("/api/v1/ad-recommend/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (response.status === 204) {
      // 没有匹配广告
      adCardEl.style.display = "none";
      emptyEl.style.display = "block";
      errorEl.style.display = "none";
      setStatus("当前没有匹配到定向广告，展示通用提示。");
      return;
    }

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = (await response.json()) as Ad;

    adTitleEl.textContent = data.title;
    adImageEl.src = data.image_url;
    adImageEl.alt = data.title;
    adLinkEl.href = data.target_url;

    adCardEl.style.display = "block";
    emptyEl.style.display = "none";
    errorEl.style.display = "none";

    setStatus("已为你匹配到专属广告");
  } catch (error) {
    console.error("Ad request error:", error);
    adCardEl.style.display = "none";
    emptyEl.style.display = "none";
    errorEl.style.display = "block";
    setStatus("加载广告失败");
  }
}

let lastGeo: { latitude: number; longitude: number; accuracy_m?: number } | null = null;

function tryGetGeo(): Promise<typeof lastGeo> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        lastGeo = {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy_m: Math.round(pos.coords.accuracy),
        };
        resolve(lastGeo);
      },
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 5000, maximumAge: 300000 }
    );
  });
}
let visitPingTimer: number | null = null;

async function postVisitPing(event: "ping" | "leave" = "ping"): Promise<void> {
  const geo = lastGeo ?? (await tryGetGeo());

  const payload = {
    latitude: geo?.latitude ?? null,
    longitude: geo?.longitude ?? null,
    accuracy_m: geo?.accuracy_m ?? null,
    event,
  };

  // 页面离开时优先用 sendBeacon（更可能发出去）
  if (event === "leave" && navigator.sendBeacon) {
    const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
    navigator.sendBeacon("/api/v1/portal/ping/", blob);
    return;
  }

  await fetch("/api/v1/portal/ping/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  });
}

function startVisitPingLoop(): void {
  if (visitPingTimer !== null) return; // 防止重复启动

  // 立刻发一次，建立初始段
  void postVisitPing("ping");

  // 每 60 秒 ping 一次
  visitPingTimer = window.setInterval(() => {
    void postVisitPing("ping");
  }, 60000);

  // 页面隐藏/关闭时，尽量收口最后一段
  const onLeave = () => {
    void postVisitPing("leave");
  };

  window.addEventListener("beforeunload", onLeave);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      onLeave();
    }
  });
}

async function acceptPortal(): Promise<void> {
  const btn = $("accept-btn") as HTMLButtonElement;
  btn.disabled = true;
  setAcceptStatus("正在提交认证...");

  try {
    const geo = lastGeo ?? (await tryGetGeo());

    const payload = {
      latitude: geo?.latitude ?? null,
      longitude: geo?.longitude ?? null,
      accuracy_m: geo?.accuracy_m ?? null,
    };

    const res = await fetch("/api/v1/portal/accept/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();

    if (data.ok) {
        startVisitPingLoop();
      if (data.venue) {
        const v = data.venue;
        setAcceptStatus(
          `认证成功。归因店铺：${v.name}（${v.category}），距离约 ${v.distance_m ?? "?"}m`
        );
      } else {
        setAcceptStatus("认证成功。但未命中附近店铺（可能未授权定位或距离阈值过小）。");
      }
    } else {
      setAcceptStatus("认证失败：返回状态异常。");
    }
  } catch (error) {
    console.error("accept portal error:", error);
    setAcceptStatus("认证失败，请稍后重试。");
  } finally {
    btn.disabled = false;
  }
}


function initPortal(): void {
  // 绑定“同意上网”按钮
  const btn = $("accept-btn");
  btn.addEventListener("click", () => {
    void acceptPortal();
  });

  setStatus("初始化中...");

  if (!("geolocation" in navigator)) {
    setStatus("设备不支持定位，展示通用广告。");
    void requestAd(null, null);
    return;
  }

  setStatus("正在请求位置信息...");

  navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;

        setStatus(`定位成功：${lat.toFixed(6)}, ${lon.toFixed(6)}（acc=${Math.round(pos.coords.accuracy)}m）`);
        void requestAd(lat, lon);
      },
      (err) => {
        setStatus(`定位失败：code=${err.code} msg=${err.message}`);
        void requestAd(null, null);
      },
      { enableHighAccuracy: false, timeout: 5000, maximumAge: 0 }
    );
}

// 页面加载完成后初始化
document.addEventListener("DOMContentLoaded", () => {
  try {
    initPortal();
  } catch (error) {
    console.error("Init portal error:", error);
    setStatus("初始化失败");
  }
});

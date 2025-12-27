"use strict";
// frontend/portal.ts
// 通用 DOM 查询工具
function $(id) {
    const el = document.getElementById(id);
    if (!el) {
        throw new Error(`Element with id "${id}" not found`);
    }
    return el;
}
function setStatus(text) {
    const statusEl = $("status");
    statusEl.textContent = text;
}
function setAcceptStatus(text) {
    const el = $("accept-status");
    el.textContent = text;
}
async function requestAd(latitude, longitude) {
    const adCardEl = $("ad-card");
    const adTitleEl = $("ad-title");
    const adImageEl = $("ad-image");
    const adLinkEl = $("ad-link");
    const emptyEl = $("empty");
    const errorEl = $("error");
    const payload = {
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
        const data = (await response.json());
        adTitleEl.textContent = data.title;
        adImageEl.src = data.image_url;
        adImageEl.alt = data.title;
        adLinkEl.href = data.target_url;
        adCardEl.style.display = "block";
        emptyEl.style.display = "none";
        errorEl.style.display = "none";
        setStatus("已为你匹配到专属广告");
    }
    catch (error) {
        console.error("Ad request error:", error);
        adCardEl.style.display = "none";
        emptyEl.style.display = "none";
        errorEl.style.display = "block";
        setStatus("加载广告失败");
    }
}
let lastGeo = null;
function tryGetGeo() {
    return new Promise((resolve) => {
        if (!navigator.geolocation)
            return resolve(null);
        navigator.geolocation.getCurrentPosition((pos) => {
            lastGeo = {
                latitude: pos.coords.latitude,
                longitude: pos.coords.longitude,
                accuracy_m: Math.round(pos.coords.accuracy),
            };
            resolve(lastGeo);
        }, () => resolve(null), { enableHighAccuracy: true, timeout: 5000, maximumAge: 300000 });
    });
}
let visitPingTimer = null;
async function postVisitPing(event = "ping") {
    var _a, _b, _c;
    const geo = lastGeo !== null && lastGeo !== void 0 ? lastGeo : (await tryGetGeo());
    const payload = {
        latitude: (_a = geo === null || geo === void 0 ? void 0 : geo.latitude) !== null && _a !== void 0 ? _a : null,
        longitude: (_b = geo === null || geo === void 0 ? void 0 : geo.longitude) !== null && _b !== void 0 ? _b : null,
        accuracy_m: (_c = geo === null || geo === void 0 ? void 0 : geo.accuracy_m) !== null && _c !== void 0 ? _c : null,
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
function startVisitPingLoop() {
    if (visitPingTimer !== null)
        return; // 防止重复启动
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
// frontend/portal.ts 里，替换你的 acceptPortal 函数为下面这个版本
async function acceptPortal() {
    const btn = $("accept-btn");
    const acceptStatus = $("accept-status");
    btn.disabled = true;
    acceptStatus.textContent = "正在提交认证...";
    try {
        const res = await fetch("/api/v1/portal/accept/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            // 目前不需要 body，后端只看 IP（以及可选的 UA）
            body: JSON.stringify({}),
        });
        // 任何非 2xx 直接当失败处理
        if (!res.ok) {
            console.error("portal accept http error:", res.status, res.statusText);
            acceptStatus.textContent = `认证失败：返回状态 ${res.status}`;
            return;
        }
        // 尝试解析 JSON（解析失败也不影响认证本身）
        let data = null;
        try {
            data = await res.json();
            console.log("portal accept response:", data);
        }
        catch (e) {
            console.warn("portal accept response is not valid JSON:", e);
        }
        // 如果有 is_authenticated 字段并且是 false，就提示警告；
        // 其它情况一律认为认证成功（因为后端 200 就已经代表成功）
        if (data && data.is_authenticated === false) {
            acceptStatus.textContent = "认证未生效，请稍后重试。";
        }
        else {
            acceptStatus.textContent = "认证成功，你可以继续访问互联网。";
        }
    }
    catch (error) {
        console.error("accept portal error:", error);
        acceptStatus.textContent = "认证失败：网络异常或服务器错误。";
    }
    finally {
        btn.disabled = false;
    }
}
function initPortal() {
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
    navigator.geolocation.getCurrentPosition((pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        setStatus(`定位成功：${lat.toFixed(6)}, ${lon.toFixed(6)}（acc=${Math.round(pos.coords.accuracy)}m）`);
        void requestAd(lat, lon);
    }, (err) => {
        setStatus(`定位失败：code=${err.code} msg=${err.message}`);
        void requestAd(null, null);
    }, { enableHighAccuracy: false, timeout: 5000, maximumAge: 0 });
}
// 页面加载完成后初始化
document.addEventListener("DOMContentLoaded", () => {
    try {
        initPortal();
    }
    catch (error) {
        console.error("Init portal error:", error);
        setStatus("初始化失败");
    }
});

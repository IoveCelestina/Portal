// src/hooks/useAdRecommendation.ts
import { useCallback, useEffect, useState } from "react";

export interface Ad {
  id: number;
  title: string;
  image_url: string;
  target_url: string;
  click_count: number;
}

export interface UseAdRecommendationResult {
  ad: Ad | null;
  loading: boolean;
  error: string | null;
  locationDenied: boolean;
  refresh: () => void;
}

/**
 * 将 user agent 交给后端解析即可，这里不做复杂处理。
 */
const getUserAgent = (): string =>
  typeof navigator !== "undefined" ? navigator.userAgent : "unknown";

/**
 * 统一封装一次 API 调用
 */
async function postAdRecommend(
  payload: Record<string, unknown>
): Promise<Ad | null> {
  const response = await fetch("/api/v1/ad-recommend/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (response.status === 204) {
    return null;
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(
      `Ad recommend request failed: ${response.status} ${text}`
    );
  }

  const data: Ad = await response.json();
  return data;
}

/**
 * useAdRecommendation Hook
 */
export function useAdRecommendation(): UseAdRecommendationResult {
  const [ad, setAd] = useState<Ad | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [locationDenied, setLocationDenied] = useState<boolean>(false);

  const fetchAd = useCallback(() => {
    setLoading(true);
    setError(null);

    const userAgent = getUserAgent();
    const localHour = new Date().getHours(); // 0-23，对应后端的 local_time 字段

    const sendRequest = async (
      latitude: number | null,
      longitude: number | null
    ) => {
      try {
        const payload: Record<string, unknown> = {
          latitude,
          longitude,
          user_agent: userAgent,
          local_time: localHour,
        };

        const adResponse = await postAdRecommend(payload);
        setAd(adResponse);
      } catch (err) {
        console.error(err);
        setError(
          err instanceof Error
            ? err.message
            : "Failed to fetch ad recommendation."
        );
      } finally {
        setLoading(false);
      }
    };

    if (
      typeof navigator === "undefined" ||
      !("geolocation" in navigator) ||
      !navigator.geolocation
    ) {
      // 浏览器不支持地理位置，直接走兜底广告
      sendRequest(null, null);
      return;
    }

    // 正常情况下，尝试获取地理位置
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        setLocationDenied(false);
        sendRequest(latitude, longitude);
      },
      (geoError) => {
        // 拒绝授权 / 超时 / 其他错误
        if (geoError.code === geoError.PERMISSION_DENIED) {
          setLocationDenied(true);
        } else {
          console.warn("Geolocation error:", geoError);
        }

        // 即使没有定位，也要请求后端，让后端走通用广告兜底
        sendRequest(null, null);
      },
      {
        enableHighAccuracy: false,
        timeout: 5000, // 超时时间 5 秒，避免卡死
        maximumAge: 0,
      }
    );
  }, []);

  useEffect(() => {
    fetchAd();
  }, [fetchAd]);

  return {
    ad,
    loading,
    error,
    locationDenied,
    refresh: fetchAd,
  };
}

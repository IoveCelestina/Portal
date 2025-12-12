import React from "react";
import { useAdRecommendation } from "../hooks/useAdRecommendation";

export const AdBanner: React.FC = () => {
  const { ad, loading, error, locationDenied, refresh } =
    useAdRecommendation();

  if (loading) {
    return (
      <div className="flex items-center justify-center p-4 text-sm text-gray-500">
        正在为你匹配附近优惠...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-sm text-red-500">
        加载广告失败：{error}
        <button
          type="button"
          className="ml-2 px-3 py-1 text-xs border rounded"
          onClick={refresh}
        >
          重试
        </button>
      </div>
    );
  }

  if (!ad) {
    return (
      <div className="flex items-center justify-center p-4 text-sm text-gray-400">
        暂时没有合适的广告
      </div>
    );
  }

  return (
    <div className="p-4">
      {locationDenied && (
        <div className="mb-2 text-xs text-gray-400">
          你未授权位置信息，展示为通用广告。
        </div>
      )}
      <a
        href={ad.target_url}
        className="block rounded-lg border shadow-sm hover:shadow-md transition-shadow"
        target="_blank"
        rel="noopener noreferrer"
      >
        <img
          src={ad.image_url}
          alt={ad.title}
          className="w-full h-auto rounded-t-lg"
        />
        <div className="p-3">
          <h2 className="text-sm font-semibold">{ad.title}</h2>
        </div>
      </a>
    </div>
  );
};

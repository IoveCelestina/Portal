# Portal/settings.py
from __future__ import annotations

from pathlib import Path
import os

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# === 基本安全配置（开发环境可写死，生产请用环境变量） ===
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "dev-secret-key-change-me",
)

DEBUG = True

# 本地开发允许所有主机，也可以只写 127.0.0.1 / localhost
ALLOWED_HOSTS: list[str] = ["*"]

# === 应用注册 ===
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # 3rd party
    "rest_framework",
    "corsheaders",

    # 本地应用
    "ads",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",

    # CORS 要放在 CommonMiddleware 之前
    "corsheaders.middleware.CorsMiddleware",

    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "Portal.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # 你根目录有 templates 文件夹，这里配置进去
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "Portal.wsgi.application"
# Portal/settings.py
#PORTAL_ALLOW_IP_SCRIPT = "/usr/local/bin/portal_allow_ip.sh" #网络配置
PORTAL_ALLOW_IP_SCRIPT = "" #windows
PORTAL_DHCP_LEASES_FILE = "/var/lib/misc/dnsmasq.leases"
ALLOWED_HOSTS = ["*"] #windows

# === 数据库配置 ===
# 默认 SQLite (开发阶段)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

"""
# 若要启用 PostgreSQL + PostGIS，示例配置如下：
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.getenv("POSTGRES_DB", "wifi_ad_beacon"),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

# 启用 PostGIS 时，INSTALLED_APPS 中需要加：
#   "django.contrib.gis",
"""


# === 密码校验器 ===
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# === 国际化 / 时区 ===
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"  # 可根据你的部署位置调整
USE_I18N = True
USE_L10N = True
USE_TZ = True


# === 静态 / 媒体文件 ===
STATIC_URL = "static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",  # 若你有前端构建产物，可以指向这里
]
STATIC_ROOT = BASE_DIR / "staticfiles"  # 收集静态文件目录 (collectstatic)

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# === Django REST framework 配置 ===
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        # 调试时想在浏览器里看漂亮的界面，可以加：
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    # 如需认证/限流/权限在这里扩展
}


# === CORS 配置（前后端域名不一致时） ===
# 开发阶段可打开以下设置；生产环境请收紧
CORS_ALLOW_ALL_ORIGINS = True

# 或者精确指定，例如：前端 Vite 在 5173 端口：
# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:5173",
#     "http://127.0.0.1:5173",
# ]

# 允许携带 Cookie 时需要：
# CORS_ALLOW_CREDENTIALS = True


# === 日志（简单示例，可按需调整） ===
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


# ========== 场所 / 设备固定部署点（用于 POI 预处理的圆心） ==========
# 广告机实际部署点的坐标（只需一次）
PORTAL_SITE_LATITUDE = 30.313601
PORTAL_SITE_LONGITUDE = 120.353372

# 预处理拉取 POI 的半径（米）：商场可 800~1500，街区可 300~800
PORTAL_POI_PRELOAD_RADIUS_M = 1000

# 在线匹配用户坐标到 POI 的最大距离（米）：超过则认为不在任何已知店铺
PORTAL_POI_MATCH_MAX_DISTANCE_M = 120

# ========== POI 数据源选择 ==========
# 先用 OVERPASS（OSM），不需要 key；后续若要更准可切 AMAP
PORTAL_POI_PROVIDER = "OVERPASS"   # "OVERPASS" | "AMAP"

# ========== Overpass（OSM）配置 ==========
# 仅当 provider=OVERPASS 时使用
PORTAL_OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
PORTAL_OVERPASS_TIMEOUT_SEC = 25

# ========== 高德（AMAP）配置（可选） ==========
# 仅当 provider=AMAP 时使用；没有就先不填
# AMAP_WEB_SERVICE_KEY = ""  # 你的高德 Web 服务 Key

# ========== 预处理任务策略 ==========
# 每次预处理前是否清理旧数据（只清理 is_active=False 或者全部由命令参数控制）
PORTAL_POI_DEACTIVATE_MISSING = False


PORTAL_VISIT_SWITCH_CONFIRMATIONS = 2
PORTAL_VISIT_INACTIVITY_TIMEOUT_SEC = 150


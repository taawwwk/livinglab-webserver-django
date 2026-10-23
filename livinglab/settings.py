import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-dev-key-change-in-production')

DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'sensor',
    'opensrc',
    'shopsense',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'livinglab.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'livinglab.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'livinglab_sensor'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
        'HOST': os.getenv('DB_HOST', 'db'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
}

# 기본 설정에서는 sensor 로거에 핸들러가 없어 logger.info()가 통째로 버려진다.
# 수집 스케줄러가 무슨 일을 했는지 docker logs로 볼 수 있어야 하므로 stdout으로 내보낸다.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        'sensor': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'opensrc': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'shopsense': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apscheduler': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}


# 오픈소스개발프로젝트 실습 API (sensor/opensrc/)
# 학생 요청 body의 "key"와 일치해야 한다 (강의자료에 공개된 값)
OPENSRC_API_KEY = os.getenv('OPENSRC_API_KEY', 'opensrc2026')
# 라즈베리파이와 공유하는 HMAC 비밀키. 절대 학생에게 공개하지 않는다.
OPENSRC_HMAC_KEY = os.getenv('OPENSRC_HMAC_KEY', '').encode()
# BLE 패킷 끝에 붙는 태그 길이(바이트). 광고 패킷 31바이트를 넘으면 4로 줄인다.
OPENSRC_TAG_LEN = int(os.getenv('OPENSRC_TAG_LEN', '8'))
# 5주차 실습: 팀 수. 팀명은 'Team 1'..'Team N', key는 'opensrc-team 1'..'opensrc-team N'
OPENSRC_TEAM_COUNT = int(os.getenv('OPENSRC_TEAM_COUNT', '9'))
# 6주차 data API의 source=lab: 팀마다 서로 다른 연구실 센서를 배정한다 (sensor_sensor_data.sensor 값).
# 2026-09-28 ~ 10-04 기준 1분 결측률이 낮은 순서로 9대를 골랐다.
OPENSRC_LAB_SENSOR_BY_TEAM = {
    'Team 1': 'sensor 20',
    'Team 2': 'sensor 01',
    'Team 3': 'sensor 26',
    'Team 4': 'sensor 21',
    'Team 5': 'sensor 14',
    'Team 6': 'sensor 06',
    'Team 7': 'sensor 33',
    'Team 8': 'sensor 15',
    'Team 9': 'sensor 04',
}
# 위 매핑에 없는 팀일 때 쓰는 기본 센서
OPENSRC_LAB_SENSOR = os.getenv('OPENSRC_LAB_SENSOR', 'sensor 01')

# 7주차 데이터 수집 실습 · 8주차 중간평가 (sensor/opensrc/check/)
# 하루 시간대: 시작 시각 9시부터 1시간 단위로 18시 전까지 (09–10 … 17–18, 9칸)
OPENSRC_SLOT_HOURS = range(int(os.getenv('OPENSRC_SLOT_START', '9')), int(os.getenv('OPENSRC_SLOT_END', '18')))
# 캠퍼스 센서 실시간 ON/OFF 판정: 최근 N분 안에 livinglab 수신(sensor_sensor_data 또는 sensor_ip_db)이 있으면 ON
OPENSRC_SENSOR_ONLINE_MINUTES = int(os.getenv('OPENSRC_SENSOR_ONLINE_MINUTES', '10'))
# IP 기록(sensor_ip_db)만으로 ON 판정할 때의 기준. 센서는 IP를 60분마다 보내므로 여유를 두고 70분.
OPENSRC_SENSOR_IP_ONLINE_MINUTES = int(os.getenv('OPENSRC_SENSOR_IP_ONLINE_MINUTES', '70'))
# 채점: 만점에서 누락 칸당 감점, 최저 0점
OPENSRC_MIDTERM_FULL_SCORE = int(os.getenv('OPENSRC_MIDTERM_FULL_SCORE', '10'))
OPENSRC_MIDTERM_PENALTY = int(os.getenv('OPENSRC_MIDTERM_PENALTY', '2'))
# 대시보드 API 결과 캐시(초). 45칸 × livinglab 조회를 폴링마다 반복하지 않도록 한다.
OPENSRC_MIDTERM_CACHE_SECONDS = int(os.getenv('OPENSRC_MIDTERM_CACHE_SECONDS', '15'))
# 수집 기간 날짜와 시간대별 담당 팀, 캠퍼스 센서 목록은 admin(수집 날짜 / 시간대 배정 / 캠퍼스 센서)에서 입력한다.

# 대학가 가게 침수 실증 (shopsense): 수위센서 API 키. 콤마로 여러 개(장비별·교체용) 지정.
# 비어 있으면 /api/shop/ 의 POST·조회 요청을 모두 거부한다. 키는 .env에만 둔다.
SHOP_API_KEYS = [k.strip() for k in os.getenv('SHOP_API_KEYS', '').split(',') if k.strip()]
# POST /api/shop/readings/ 의 API 키당 허용 횟수 (DRF 형식: '60/min', '1000/hour' 등).
# 파이 1대는 정상 시 분당 6회, 밀린 데이터 재전송 중에도 분당 30회 이내로 보낸다.
SHOP_POST_RATE = os.getenv('SHOP_POST_RATE', '60/min')
SHOP_THROTTLE_CACHE = 'shopsense_throttle'

CACHES = {
    # 기존과 같은 기본값 (명시만 함)
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
    # shopsense rate limit 카운터. gunicorn worker들이 같은 컨테이너의 파일을 공유해야
    # 키당 한도가 worker 수만큼 늘어나지 않는다. 컨테이너를 재생성하면 초기화된다.
    SHOP_THROTTLE_CACHE: {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': '/tmp/shopsense_throttle',
    },
}

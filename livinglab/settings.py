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
# 6주차 data API의 source=lab이 내보내는 연구실 센서 (sensor_sensor_data.sensor 값)
OPENSRC_LAB_SENSOR = os.getenv('OPENSRC_LAB_SENSOR', 'sensor 01')

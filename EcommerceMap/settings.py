import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv()
# OR, the same with increased verbosity
load_dotenv(verbose=True)
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-e8b@m!mq(=z%^wu4hgn2i^t#sr2!+j28$m)cd1r+j&3kmq#^wo'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    'allauth',
    'allauth.account',
    'accounts',
    'core',
    'crispy_forms',
    'crispy_bootstrap5',
    'import_export',
    'rest_framework',
    'connects',
]
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
USE_DJANGO_JQUERY = True
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'EcommerceMap.urls'
AUTH_USER_MODEL = 'accounts.User'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates']
        ,
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

WSGI_APPLICATION = 'EcommerceMap.wsgi.application'

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': 'ecommerce_map_db',
        'USER': 'postgres',
        'PASSWORD': '123456',
        'HOST': 'db',
        'PORT': '5432',

    }
}

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

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

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True
ADMIN_SITE_HEADER = "Ecommerce MAP"
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = 'static/'
# STATIC_ROOT = os.path.join(BASE_DIR, 'static')
STATICFILES_DIRS = [BASE_DIR / 'static', ]

REST_FRAMEWORK = {

    #  allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly'
    ]
}

# All Auth Setting

# ACCOUNT_AUTHENTICATION_METHOD = 'email'
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# GDAL_LIBRARY_PATH = r'C:\Users\junaid iqbal\PycharmProjects\EcommerceMap\.venv\Lib\site-packages\osgeo\gdal304.dll'
# GEOS_LIBRARY_PATH = r'C:\Users\junaid iqbal\PycharmProjects\EcommerceMap\.venv\Lib\site-packages\osgeo\geos_c.dll'

STRIPE_SECRET_KEY = os.getenv('STRIPE_TEST_SECRET_KEY')
STRIPE_WEBHOOK_SECRET_KEY = os.getenv('STRIPE_WEBHOOK_SECRET_KEY')
STRIPE_SUCCESS_URL = os.getenv('STRIPE_SUCCESS_URL')
STRIPE_CANCEL_URL = os.getenv('STRIPE_CANCEL_URL')
STRIPE_BILLING_PORTAL = os.getenv('STRIPE_BILLING_PORTAL')

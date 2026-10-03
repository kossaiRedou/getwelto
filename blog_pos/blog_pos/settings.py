
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env (absent en production Docker :
# la configuration y est fournie par les variables d'environnement de Coolify).
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
if os.path.exists(env_path):
    # override=True : le .env du projet fait autorité sur les variables
    # ambiantes (ex: DEBUG=* posé globalement par l'écosystème npm/debug).
    load_dotenv(env_path, override=True)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'

# Dossier de données persistantes (volume Docker /data en production)
USER_DATA_PATH = os.getenv('WELTO_USER_DATA', None)

if USER_DATA_PATH:
    DATA_DIR = Path(USER_DATA_PATH) / 'data'
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH = DATA_DIR / 'db.sqlite3'
    MEDIA_DIR = Path(USER_DATA_PATH) / 'media'
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DB_PATH = Path(BASE_DIR) / 'db.sqlite3'
    MEDIA_DIR = Path(BASE_DIR) / 'media'


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
def _load_or_create_secret_key():
    """Retourne la SECRET_KEY de l'application.

    Priorité 1 : variable d'environnement SECRET_KEY (recommandé côté serveur/SaaS).
    Priorité 2 : clé persistante générée automatiquement et stockée HORS du dépôt
                 (userData en production, BASE_DIR en développement).

    Aucune clé partagée codée en dur : chaque installation obtient sa propre clé,
    ce qui évite la falsification de sessions/tokens entre installations.
    """
    env_key = os.getenv('SECRET_KEY')
    if env_key:
        return env_key

    key_dir = Path(USER_DATA_PATH) if USER_DATA_PATH else Path(BASE_DIR)
    key_dir.mkdir(parents=True, exist_ok=True)
    key_file = key_dir / 'secret_key.txt'

    if key_file.exists():
        existing = key_file.read_text(encoding='utf-8').strip()
        if existing:
            return existing

    from django.core.management.utils import get_random_secret_key
    new_key = get_random_secret_key()
    key_file.write_text(new_key, encoding='utf-8')
    try:
        os.chmod(key_file, 0o600)  # lecture/écriture propriétaire uniquement
    except Exception:
        pass
    return new_key


SECRET_KEY = _load_or_create_secret_key()

# SECURITY WARNING: don't run with debug turned on in production!
# Piloté par l'environnement. Défaut = False (sûr). En dev, mettre DEBUG=True dans .env.
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    '*.localhost',  # Sous-domaines localhost si nécessaire
]

# Hôtes supplémentaires via l'environnement (ex: domaine SaaS "api.welto.app,welto.app")
_extra_hosts = os.getenv('ALLOWED_HOSTS', '')
if _extra_hosts:
    ALLOWED_HOSTS += [h.strip() for h in _extra_hosts.split(',') if h.strip()]

# Origines de confiance pour la protection CSRF (requis en HTTPS / cross-origin, ex: SaaS)
# Format env: "https://welto.app,https://api.welto.app"
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'core',
    'product',
    'order',
    'client',
    'aprovision',
    'users',
]

# Configuration du modèle utilisateur personnalisé
AUTH_USER_MODEL = 'users.User'

# Configuration de l'authentification
LOGIN_URL = '/users/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/users/login/'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Servir fichiers statiques en production
    'django.middleware.gzip.GZipMiddleware',  # Pages et JSON compressés (connexions lentes)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',  # Réactivé : protection CSRF (requis dès accès réseau)
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',  # Nécessaire pour les messages Django
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'users.middleware.SetupMiddleware',  # Middleware pour la configuration initiale
]

ROOT_URLCONF = 'blog_pos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'users.context_processors.app_settings',  # currency + company_name
            ],
        },
    },
]

WSGI_APPLICATION = 'blog_pos.wsgi.application'


# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases
# Utilise userData en production pour la persistance lors des mises à jour

# PostgreSQL en production, SQLite en développement local rapide.
# Deux façons de configurer PostgreSQL :
#   DATABASE_URL=postgres://user:mot_de_passe@hote:5432/base   (format fourni par Coolify)
#   ou DB_ENGINE=postgres + DB_NAME / DB_USER / DB_PASSWORD / DB_HOST / DB_PORT
_database_url = os.getenv('DATABASE_URL', '').strip()
if _database_url:
    from urllib.parse import unquote, urlparse
    _db = urlparse(_database_url)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': unquote(_db.path.lstrip('/')),
            'USER': unquote(_db.username or ''),
            'PASSWORD': unquote(_db.password or ''),
            'HOST': _db.hostname or 'localhost',
            'PORT': str(_db.port or 5432),
            'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
        }
    }
elif os.getenv('DB_ENGINE', 'sqlite').lower() == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'welto'),
            'USER': os.getenv('DB_USER', 'welto'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(DB_PATH),
            'OPTIONS': {
                'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;',
            },
        }
    }


# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/2.0/topics/i18n/

LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', 'fr-fr')  # Français pour l'interface WELTO

TIME_ZONE = os.getenv('TIME_ZONE', 'Africa/Dakar')  # Timezone Afrique de l'Ouest

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_URL = '/static/'

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Whitenoise : fichiers hashés + précompressés (gzip/brotli), cache navigateur 1 an.
# collectstatic est obligatoire en production (fait dans le Dockerfile).
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': (
        'django.contrib.staticfiles.storage.StaticFilesStorage' if TESTING
        else 'whitenoise.storage.CompressedManifestStaticFilesStorage')},
}
WHITENOISE_MAX_AGE = 31536000

# Configuration de sécurité.
# En production, l'app tourne derrière un reverse proxy (Coolify/Traefik) qui
# termine le TLS, lui-même derrière Cloudflare. WELTO_HTTPS=true active les
# cookies Secure et la détection du scheme via X-Forwarded-Proto.
_HTTPS = os.getenv('WELTO_HTTPS', 'False').lower() == 'true'

SECURE_SSL_REDIRECT = False          # La redirection HTTP→HTTPS se fait au proxy/Cloudflare
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_SECURE = _HTTPS
CSRF_COOKIE_SECURE = _HTTPS
if _HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Journalisation : console + fichier rotatif dans userData (production) ou BASE_DIR (dev)
_LOG_DIR = (Path(USER_DATA_PATH) / 'logs') if USER_DATA_PATH else (Path(BASE_DIR) / 'logs')
_LOG_DIR.mkdir(parents=True, exist_ok=True)

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
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(_LOG_DIR / 'welto.log'),
            'maxBytes': 2 * 1024 * 1024,  # 2 Mo
            'backupCount': 3,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {'level': 'WARNING'},
    },
}

# Media files (User uploads)
# Utilise userData en production pour la persistance
MEDIA_URL = '/media/'
MEDIA_ROOT = str(MEDIA_DIR)

CURRENCY = os.getenv('CURRENCY', 'GNF')

# ============================================
# Email (récupération de mot de passe par code)
# ============================================
# Nécessite une connexion Internet côté client. Configuration via .env :
#   EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD,
#   EMAIL_USE_TLS/EMAIL_USE_SSL, DEFAULT_FROM_EMAIL
# Si aucun EMAIL_HOST n'est fourni :
#   - en DEBUG : les emails sont affichés dans la console (backend console) ;
#   - en production : backend SMTP par défaut (échouera proprement si non joignable).
_email_host = os.getenv('EMAIL_HOST', '').strip()
if _email_host:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = _email_host
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
    EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
    EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '20'))
elif DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'WELTO <no-reply@welto.app>')

# Configuration par défaut pour les clés primaires
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
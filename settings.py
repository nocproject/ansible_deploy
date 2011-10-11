# Django settings for noc project.
# Do not modify this file directly
# Edit etc/noc.conf instead
import ConfigParser, sys

config=ConfigParser.SafeConfigParser()
config.read(["etc/noc.defaults","etc/noc.conf"])
if not config.sections():
    # Called from autodoc
    config.read(["../../../../etc/noc.defaults","../../../../etc/noc.conf"])

DEBUG = config.get("main","debug")
TEMPLATE_DEBUG = DEBUG

## Set up admins
## @todo: remove
ADMINS = []
for a in config.get("main", "admin_emails").split(","):
    a = a.strip()
    if not a:
        continue
    n, d = a.split("@")
    ADMINS.append((n, a))

MANAGERS = ADMINS

SERVER_EMAIL      = config.get("main", "server_email")

## RDBMS settings
DATABASE_ENGINE   = config.get("database", "engine")
DATABASES={
    "default" : {
        "ENGINE"   : "django.db.backends." + config.get("database", "engine"),
        "NAME"     : config.get("database","name"),
        "USER"     : config.get("database","user"),
        "PASSWORD" : config.get("database","password"),
        "HOST"     : config.get("database","host"),
        "PORT"     : config.get("database","port"),
        "TEST_NAME": "test_" + config.get("database", "name")
    }
}
DATABASE_SUPPORTS_TRANSACTIONS = True
## NoSQL settings
NOSQL_DATABASE_NAME = config.get("nosql_database", "name")
NOSQL_DATABASE_TEST_NAME = NOSQL_DATABASE_NAME + "_test"
NOSQL_DATABASE_USER = config.get("nosql_database", "user")
NOSQL_DATABASE_PASSWORD = config.get("nosql_database", "password")
NOSQL_DATABASE_HOST = config.get("nosql_database", "host")
NOSQL_DATABASE_PORT = config.get("nosql_database", "port")

TIME_ZONE = config.get("main","timezone")
LANGUAGE_CODE = config.get("main","language_code")
# Set up date and time formats
DATE_FORMAT      = config.get("main","date_format")
TIME_FORMAT      = config.get("main","time_format")
MONTH_DAY_FORMAT = config.get("main","month_day_format")
YEAR_MONTH_FORMAT= config.get("main","year_month_format")
DATETIME_FORMAT  = config.get("main","datetime_format")

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = ""

# URL that handles the media served from MEDIA_ROOT.
# Example: "http://media.lawrence.com"
MEDIA_URL = ""

# URL prefix for admin media -- CSS, JavaScript and images. Make sure to use a
# trailing slash.
# Examples: "http://foo.com/media/", "/media/".
ADMIN_MEDIA_PREFIX = "/media/"

# Make this unique, and don"t share it with anybody.
SECRET_KEY = config.get("main","secret_key")

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = [
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader"
]
# 
TEMPLATE_CONTEXT_PROCESSORS= (
    "django.contrib.auth.context_processors.auth",
    "django.core.context_processors.debug",
    "django.core.context_processors.i18n",
    "django.core.context_processors.media",
    "django.contrib.messages.context_processors.messages",
    "noc.lib.app.setup_processor",
    )
#
MIDDLEWARE_CLASSES = [
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "noc.lib.middleware.HTTPBasicAuthMiddleware",
    "django.middleware.doc.XViewMiddleware",
    "django.middleware.transaction.TransactionMiddleware",
    "noc.lib.middleware.TLSMiddleware", # Thread local storage
]

if config.get("authentication", "method") == "http":
    MIDDLEWARE_CLASSES += ["django.contrib.auth.middleware.RemoteUserMiddleware"]

ROOT_URLCONF = "noc.urls"

TEMPLATE_DIRS = (
    # Put strings here, like "/home/html/django_templates" or "C:/www/django/templates".
    # Always use forward slashes, even on Windows.
    # Don"t forget to use absolute paths, not relative paths.
    "local",
    ".",
    "templates"
)

CACHE_BACKEND = "locmem:///"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.admin",
    "django.contrib.messages",
    #"django.contrib.databrowse",
    "tagging",
    "south",
    
    "noc.main",
    "noc.inv",
    "noc.sa",
    "noc.fm",
    "noc.pm",
    "noc.cm",
    "noc.ip",
    "noc.vc",
    "noc.dns",
    "noc.peer",
    "noc.kb"
]
# Populate list of locally-installed apps
apps = config.get("main","installed_apps").strip()
if apps:
    INSTALLED_APPS += [app.strip() for app in apps.split(",")]

FORCE_SCRIPT_NAME = ""

# Available languages
_ = lambda s: s
LANGUAGES = [
    ("en", _("English")),
    ("ru", _("Russian")),
]

#SOUTH_AUTO_FREEZE_APP = False

AUTH_PROFILE_MODULE = "main.UserProfile"
##
## Determine WEB process
##
IS_WEB = ((len(sys.argv) >= 2 and sys.argv[0] == "manage.py" and
          sys.argv[1] in ["runserver", "test", "sync-perm"])
    or sys.argv[0].endswith("noc-web.py"))
IS_TEST = len(sys.argv) >= 2 and sys.argv[:2] == ["manage.py", "test"]
##
## Coverage wrapper
##
COVERAGE_REPORT_PATH="local/coverage_report"
SKIP_SOUTH_TESTS = True
SOUTH_TESTS_MIGRATE = True
##
LOGIN_URL="/main/auth/login/"  # @todo: remove
## Do not enforce lowercase tags
FORCE_LOWERCASE_TAGS=False
## Message application setup
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
## Store sessions in mongodb
SESSION_ENGINE = "mongoengine.django.sessions"
## Set up logging
## Disable SQL statement logging
import logging

logging.getLogger("django.db.backends").setLevel(logging.ERROR)

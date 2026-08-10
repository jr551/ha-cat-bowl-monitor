"""Constants for Cat Bowl Monitor."""

DOMAIN = "cat_bowl_monitor"
PLATFORMS = ["binary_sensor", "button", "camera", "sensor"]

CONF_CAMERA_ENTITY = "camera_entity"
CONF_LIGHT_ENTITY = "light_entity"
CONF_CONFIRMATION_SAMPLES = "confirmation_samples"
CONF_CONFIDENCE_THRESHOLD = "confidence_threshold"
CONF_NOTIFICATIONS = "notifications"
CONF_NOTIFY_NO_ACTION = "notify_no_action"
CONF_NOTIFICATION_SERVICE = "notification_service"
CONF_RIGHT_FEED_ENTITY = "right_feed_entity"
CONF_LEFT_FEED_ENTITY = "left_feed_entity"
CONF_FEEDING_SENSOR = "feeding_sensor"
CONF_MORNING_TIME = "morning_time"
CONF_AFTERNOON_TIME = "afternoon_time"
CONF_CHECK_INTERVAL_HOURS = "check_interval_hours"
CONF_NIGHT_CHECK_INTERVAL_HOURS = "night_check_interval_hours"
CONF_PET_NAME = "pet_name"
CONF_BOWL_DESCRIPTION = "bowl_description"
CONF_AI_API_KEY = "ai_api_key"
CONF_AI_BASE_URL = "ai_base_url"
CONF_AI_MODEL = "ai_model"

DEFAULT_CONFIRMATION_SAMPLES = 2
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_NOTIFICATIONS = False
DEFAULT_NOTIFY_NO_ACTION = False
DEFAULT_MORNING_TIME = "05:00"
DEFAULT_AFTERNOON_TIME = "16:00"
DEFAULT_CHECK_INTERVAL_HOURS = 0
DEFAULT_NIGHT_CHECK_INTERVAL_HOURS = 0
DEFAULT_PET_NAME = "Cat"
DEFAULT_BOWL_DESCRIPTION = (
    "PRIMARY DRY is the rectangular metal tray in the upper-left/centre "
    "(approximately x=5-55%, y=15-75%); it alone controls feeding. SECONDARY "
    "is any clearly visible separate wet-food, treat, or temporary bowl in the "
    "right/lower-right area (approximately x=60-100%, y=45-100%). Report "
    "SECONDARY as unknown when no separate bowl is clearly visible."
)

MIN_CONFIRMATION_SAMPLES = 2
MAX_CONFIRMATION_SAMPLES = 6
CHECK_INTERVAL_OPTIONS = (0, 2, 3, 4, 6, 8, 12, 24)
CONFIRMATION_DELAY_SECONDS = 30
POST_FEED_SETTLE_SECONDS = 120
POST_FEED_BASELINE_RETRY_SECONDS = (60, 300, 900)
SAFETY_FALLBACK_AFTER_HOURS = 8
SAFETY_FALLBACK_COOLDOWN_HOURS = 12
SCHEDULE_CATCHUP_MINUTES = 20

UBOX_DOMAIN = "ubox_camera"
UBOX_CONF_AI_API_KEY = "ai_api_key"
UBOX_CONF_AI_BASE_URL = "ai_base_url"
UBOX_CONF_AI_MODEL = "ai_model"

STORE_VERSION = 1
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024
MAX_SUMMARY_LENGTH = 500
PROVIDER_TIMEOUT = 90
PROVIDER_PARSE_ATTEMPTS = 3
CAPTURE_TIMEOUT = 20
MAX_CAMERA_IMAGE_BYTES = 4 * 1024 * 1024
CAT_PHOTO_DEDUPE_MINUTES = 30
ILLUMINATION_SETTLE_SECONDS = 5
MAX_CONSECUTIVE_FAILURES_BEFORE_UNAVAILABLE = 3

EVENT_CHECKED = f"{DOMAIN}_checked"
EVENT_BECAME_EMPTY = f"{DOMAIN}_became_empty"
EVENT_RECOVERED = f"{DOMAIN}_recovered"
EVENT_SCHEDULED_CYCLE = f"{DOMAIN}_scheduled_cycle"
EVENT_FEED_REQUESTED = f"{DOMAIN}_feed_requested"
EVENT_BASELINE_RESET = f"{DOMAIN}_baseline_reset"

"""Constants for Cat Bowl Monitor."""

DOMAIN = "cat_bowl_monitor"
PLATFORMS = ["binary_sensor", "button", "camera", "sensor"]

CONF_CAMERA_ENTITY = "camera_entity"
CONF_LIGHT_ENTITY = "light_entity"
CONF_CONFIRMATION_SAMPLES = "confirmation_samples"
CONF_CONFIDENCE_THRESHOLD = "confidence_threshold"
CONF_NOTIFICATIONS = "notifications"
CONF_NOTIFICATION_SERVICE = "notification_service"
CONF_RIGHT_FEED_ENTITY = "right_feed_entity"
CONF_LEFT_FEED_ENTITY = "left_feed_entity"
CONF_FEEDING_SENSOR = "feeding_sensor"
CONF_MORNING_TIME = "morning_time"
CONF_AFTERNOON_TIME = "afternoon_time"
CONF_PET_NAME = "pet_name"
CONF_BOWL_DESCRIPTION = "bowl_description"
CONF_AI_API_KEY = "ai_api_key"
CONF_AI_BASE_URL = "ai_base_url"
CONF_AI_MODEL = "ai_model"

DEFAULT_CONFIRMATION_SAMPLES = 2
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_NOTIFICATIONS = False
DEFAULT_MORNING_TIME = "05:00"
DEFAULT_AFTERNOON_TIME = "16:00"
DEFAULT_PET_NAME = "Cat"
DEFAULT_BOWL_DESCRIPTION = (
    "DRY is the main dry-food bowl. WET is the separate secondary wet-food "
    "bowl. Judge only food inside those two bowls."
)

MIN_CONFIRMATION_SAMPLES = 2
MAX_CONFIRMATION_SAMPLES = 6
CONFIRMATION_DELAY_SECONDS = 30
POST_FEED_SETTLE_SECONDS = 90
SCHEDULE_CATCHUP_MINUTES = 20

UBOX_DOMAIN = "ubox_camera"
UBOX_CONF_AI_API_KEY = "ai_api_key"
UBOX_CONF_AI_BASE_URL = "ai_base_url"
UBOX_CONF_AI_MODEL = "ai_model"

STORE_VERSION = 1
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024
MAX_SUMMARY_LENGTH = 500
PROVIDER_TIMEOUT = 60
CAPTURE_TIMEOUT = 20
ILLUMINATION_SETTLE_SECONDS = 2
MAX_CONSECUTIVE_FAILURES_BEFORE_UNAVAILABLE = 3

EVENT_CHECKED = f"{DOMAIN}_checked"
EVENT_BECAME_EMPTY = f"{DOMAIN}_became_empty"
EVENT_RECOVERED = f"{DOMAIN}_recovered"
EVENT_SCHEDULED_CYCLE = f"{DOMAIN}_scheduled_cycle"
EVENT_FEED_REQUESTED = f"{DOMAIN}_feed_requested"
EVENT_BASELINE_RESET = f"{DOMAIN}_baseline_reset"

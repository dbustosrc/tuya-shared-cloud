"""Constants for the Tuya Shared Cloud integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tuya_shared_cloud"

CONF_ACCESS_ID: Final = "access_id"
CONF_ACCESS_SECRET: Final = "access_secret"
CONF_REGION: Final = "region"
CONF_UID: Final = "uid"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_REGION: Final = "us"
# Cloud push is the primary update path. This interval only reconciles state in
# case Tuya drops an event while the MQTT connection is being renewed.
DEFAULT_SCAN_INTERVAL: Final = 600
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 3600
SHARED_DEVICE_PAGE_SIZE: Final = 100

PUSH_PROTOCOL_DEVICE_REPORT: Final = 4
PUSH_PROTOCOL_OTHER: Final = 20
PUSH_BIZCODE_ONLINE: Final = "online"
PUSH_BIZCODE_OFFLINE: Final = "offline"
PUSH_CONFIG_RENEW_MARGIN: Final = 120
PUSH_CONNECT_TIMEOUT: Final = 20
PUSH_RETRY_MIN: Final = 30
PUSH_RETRY_MAX: Final = 900

REGION_ENDPOINTS: Final = {
    "us": "https://openapi.tuyaus.com",
    "eu": "https://openapi.tuyaeu.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}

DP_DOOR_CONTACT: Final = "doorcontact_state"
DP_DOOR_CONTROL: Final = "door_control_1"
DP_VOICE_CONTROL: Final = "voice_control_1"

DOOR_OPEN: Final = "open"
DOOR_CLOSE: Final = "close"

PENDING_COMMAND_TIMEOUT: Final = 90

DP_NAMES: Final = {
    "switch_1": "Relay",
    "countdown_1": "Relay countdown",
    "doorcontact_state": "Door contact",
    "tr_timecon": "Relay activation time",
    "countdown_alarm": "Open-door alarm delay",
    "door_control_1": "Door control",
    "voice_control_1": "Voice control",
    "door_state_1": "Door alarm state",
}

DP_ICONS: Final = {
    "switch_1": "mdi:electric-switch",
    "countdown_1": "mdi:timer-sand",
    "doorcontact_state": "mdi:garage",
    "tr_timecon": "mdi:timer-cog-outline",
    "countdown_alarm": "mdi:alarm",
    "door_control_1": "mdi:garage-open-variant",
    "voice_control_1": "mdi:microphone",
    "door_state_1": "mdi:garage-alert-variant",
}

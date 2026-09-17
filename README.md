# Tuya Shared Cloud

A Home Assistant custom integration for Tuya devices received through
**individual device sharing**. It is designed for devices that are visible in
Smart Life and through Tuya OpenAPI with `from=sharing`, but are not enumerated
by Home Assistant's official Tuya integration.

## Important behavior

- Imports **only** devices returned by:

  ```http
  GET /v1.0/users/{uid}/devices?from=sharing
  ```

- Does not import devices owned by your account, avoiding duplicates with the
  official Tuya integration.
- Does not need LAN access, a VPN, or a Tuya `local_key`.
- Stores the Access ID, Access Secret, region, and UID in the Home Assistant
  config entry.
- Obtains short-lived Tuya tokens automatically and replaces them before they
  expire. Manual reauthentication is requested only if Tuya rejects the stored
  project credentials.
- Discovers the functions and status values of every shared device.
- Receives device reports through Tuya OpenMQ (cloud push) and filters every
  report against the current `from=sharing` inventory.
- Reconciles authoritative REST status every 10 minutes by default. This is a
  safety net, not the primary update path.

## State updates and diagnostics

Tuya OpenMQ is the normal state source. A third-party action should therefore
reach Home Assistant as soon as Tuya publishes its device report, without
waiting for the REST reconciliation interval.

The integration renews short-lived MQTT credentials before they expire and
retries failed connections with bounded exponential backoff. If push is
temporarily unavailable, entities remain usable and the slow REST
reconciliation continues.

Home Assistant's **Download diagnostics** output contains only counters and
connection state, never credentials or device values. In particular:

- `subscribed` proves that the broker acknowledged the source-topic
  subscription.
- `datapoints_applied` counts state changes delivered by push.
- `reconciliation_corrections` counts state changes that the slow REST pass had
  to recover.
- `delivery_ratio` is the proportion of observed changes delivered by push.

## Entities

The integration maps every datapoint exposed by Tuya:

| Tuya type | Home Assistant entity |
| --- | --- |
| Writable Boolean | Switch |
| Writable Integer | Number |
| Writable Enum | Select |
| Read-only Boolean | Binary sensor |
| Other read-only value | Sensor |

Garage door devices with `door_control_1` additionally receive a garage
`cover` entity whose physical state comes from `doorcontact_state`. The raw
datapoint entities remain available, including close commands even when the
physical controller is configured to ignore them.

## Installation with HACS

1. Open the repository in HACS:

   [![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dbustosrc&repository=tuya-shared-cloud&category=integration)

   Alternatively, add `https://github.com/dbustosrc/tuya-shared-cloud` to HACS
   as a **Custom repository** of type **Integration**.
2. Install **Tuya Shared Cloud**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**.
5. Search for **Tuya Shared Cloud**.

## Configuration

The UI asks for:

- Tuya Cloud region.
- Access ID / Client ID.
- Access Secret / Client Secret.
- UID of the linked Smart Life/Tuya account.
- Safety reconciliation interval (600 seconds by default).

The Tuya Cloud project must authorize **IoT Core** and **Smart Home Basic
Service**, and the Smart Life account must be linked to the project. Cloud push
also requires an active **Device Status Notification** subscription and project
authorization. Verify both **My Subscriptions** and **Authorized Projects** in
the Tuya platform. The integration uses Tuya's Smart Home OpenMQ endpoint and
message encryption 1.0; this is distinct from the similarly named custom
OpenAPI endpoint under `/iot-03`. Configuration is rejected with an explicit
error if OpenMQ access is not available, so the integration cannot silently
start in polling-only mode.

## Safety

Commands are sent directly through Tuya Cloud. Test physical actuators only
when the surrounding area is clear and the action has been explicitly
authorized.

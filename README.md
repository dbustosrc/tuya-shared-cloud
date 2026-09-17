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

Garage door devices in Tuya category `ckmkzq` with a Boolean `switch_1`
function additionally receive:

- a garage `cover` controlled through the standard `switch_1` datapoint;
- an optional stateless **Trigger door** button; and
- a physical state derived from `doorcontact_state` only when that contact is
  configured as trustworthy.

The raw datapoint entities remain available, including `switch_1`,
`door_control_1`, and close commands even when the physical controller is
configured to ignore them. A successful Tuya API acknowledgement is not treated
as a device-state change: entities update only after OpenMQ push or REST confirms
the value.

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

### Quick reference: what to enter in each field

| Home Assistant field | Value to enter | Where to find it |
| --- | --- | --- |
| **Cloud region** | The data center used by the Tuya cloud project | Tuya project **Overview**, or the data-center selector in the top-right corner of the project |
| **Access ID / Client ID** | The project's Access ID | Tuya project **Overview → Authorization Key** |
| **Access Secret / Client Secret** | The project's Access Secret | Tuya project **Overview → Authorization Key** |
| **Smart Life / Tuya UID** | The UID of the linked app account that **received the individually shared devices** | Tuya project **Devices → Link Tuya App Account** |
| **Safety reconciliation interval** | Leave `600` unless you have a specific reason to change it | This is a slow REST safety check, in seconds; it is not the cloud-push delay |

Do **not** enter a Tuya access token, device ID, email address, telephone
number, Smart Life password, or device `local_key`. The integration creates and
renews its own short-lived API and OpenMQ credentials.

### 1. Create or open the correct Tuya cloud project

1. Sign in to the [Tuya Developer Platform](https://platform.tuya.com/).
2. Go to **Cloud → Cloud Project → Project Management**. In older versions of
   the Tuya interface this can appear as **Cloud → Development**.
3. Open an existing project, or select **Create Cloud Project**.
4. For a new project, select **Smart Home** as the development method.
5. Select the data center that serves the region of the Smart Life/Tuya app
   account. In the mobile app you can check the account region under
   **Me → Settings → Account and Security → Region**.

Tuya isolates accounts and projects by data center. If the project uses the
wrong data center, linking the app account might fail or the project might show
no devices. See Tuya's official
[data-center mapping](https://developer.tuya.com/en/docs/iot/oem-app-data-center-distributed?id=Kafi0ku9l07qb)
if you are unsure.

The integration currently exposes these region choices:

| Integration option | Tuya project data center | API endpoint |
| --- | --- | --- |
| **United States** | Western America Data Center | `https://openapi.tuyaus.com` |
| **Europe** | Central Europe Data Center | `https://openapi.tuyaeu.com` |
| **China** | China Data Center | `https://openapi.tuyacn.com` |
| **India** | India Data Center | `https://openapi.tuyain.com` |

The **United States** option refers to Tuya's Western America endpoint; it does
not refer to the country configured in Home Assistant. If the project is hosted
in Eastern America, Western Europe, or Singapore, do not select an approximate
region: those newer endpoints are not supported by the current integration.

### 2. Subscribe to and authorize the required Tuya services

The project needs all of the following:

- **IoT Core**, with an active resource pack or plan.
- **Smart Home Basic Service**.
- **Device Status Notification**, for real-time cloud push.

Open **Cloud Services** in the Tuya platform, locate each service, and subscribe
or authorize it for the cloud project. For **Device Status Notification**, check
both tabs on its service page:

1. **My Subscriptions** must show the service as active or **In service**.
2. **Authorized Projects** must list the cloud project used by this integration.

Tuya can take several minutes to activate a newly enabled message service. Its
documentation notes that message-service or data-center changes can take up to
about 30 minutes to become effective.

### 3. Link the Smart Life/Tuya account and obtain its UID

1. Open the cloud project.
2. Go to **Devices → Link Tuya App Account**.
3. Select **Add App Account**.
4. In the Smart Life or Tuya Smart mobile app, sign in to the account that
   **received the individual device share**.
5. Use that app to scan the QR code displayed by the Tuya Developer Platform,
   then confirm the authorization in the app.
6. Select **Automatic Link**. If Tuya asks for device permissions, allow
   **Read, Write, and Manage** so Home Assistant can expose both status and
   controls.
7. After the account appears in the linked-account list, copy its **UID**.

Use the UID shown on this linked-account page. It is not the device ID, project
ID, Access ID, email address, or phone number. If one Smart Life account owns a
device and another account received it through Tuya's individual sharing
feature, link and use the UID of the **recipient** account.

Tuya documents the same linking procedure in
[Link Devices](https://developer.tuya.com/en/docs/iot/link-devices?id=Ka471nu1sfmkl)
and its
[cloud API key guide](https://developer.tuya.com/en/docs/developer/apply-cloud-api-key?id=Kff30z8sv62ah).

### 4. Copy the Access ID and Access Secret

1. Return to the cloud project's **Overview** page.
2. Find **Authorization Key**.
3. Copy **Access ID / Client ID** into the Home Assistant **Access ID / Client
   ID** field.
4. Reveal and copy **Access Secret / Client Secret** into the corresponding
   password field.

Treat the Access Secret like a password. Do not place it in `configuration.yaml`,
logs, screenshots, Git commits, issue reports, or diagnostics. Home Assistant
stores it in the integration's config entry.

### 5. Optionally verify the shared-device inventory

Before configuring Home Assistant, you can verify the account without operating
any physical device. In Tuya's **API Explorer**, select the same project and data
center, then call:

```http
GET /v1.0/users/{uid}/devices?from=sharing
```

Replace `{uid}` with the linked-account UID. A successful response must contain
the devices that were individually shared with that account. Devices owned by
the account are intentionally absent from this result and from this integration.

### 6. Complete the Home Assistant form

Enter the four values obtained above and leave **Safety reconciliation
interval** at `600` seconds for normal use. The allowed range is 60 to 3600
seconds. Cloud push remains the primary state source; this interval only repairs
state if an event was missed while the OpenMQ connection was reconnecting.

When you submit the form, the integration verifies all of the following before
saving the entry:

- the project credentials and selected region;
- that the UID has at least one individually shared device; and
- that Smart Home OpenMQ cloud push is authorized.

The integration uses Tuya's Smart Home OpenMQ endpoint and message encryption
1.0. This is distinct from the similarly named custom OpenAPI endpoint under
`/iot-03`. The integration does not silently fall back to polling-only mode.

## Garage-door product options

Tuya garage controllers from different manufacturers do not always use the
same Boolean polarity, and some report a contact value that is inverted or does
not change at all. Configure these quirks without editing YAML or code:

1. Open **Settings → Devices & services**.
2. Find **Tuya Shared Cloud**, open its menu, and select **Configure**.
3. Choose the garage door.
4. Set these options independently:

| Option | Enable it when |
| --- | --- |
| **Invert open and close command values** | `switch_1=false` operates the door while `switch_1=true` does not, or open and close are otherwise reversed. |
| **Invert the reported door-contact state** | The contact reliably changes but reports open as closed and closed as open. |
| **Trust the reported door-contact state** | `doorcontact_state` reliably follows the physical door. Disable it if the value is stuck or inconsistent. |
| **Create a stateless door trigger button** | You want one action that sends the configured open/trigger value without guessing the current state. |

When trusted status is disabled, the cover deliberately reports an unknown,
assumed state. This avoids showing a successful movement that never occurred.
The stateless trigger button remains usable and sends exactly one command; it
does not send an automatic second pulse and does not inspect the unreliable
contact.

Home Assistant's standard `cover.toggle` action is available for covers whose
contact state is trustworthy. It is not a safe toggle mechanism when the device
cannot report whether the physical door is open or closed; use the stateless
trigger button for that hardware.

### Common configuration errors

| Error shown by Home Assistant | What to check |
| --- | --- |
| **Tuya rejected the project credentials** | Confirm the Access ID and Access Secret belong to the selected project and that **Cloud region** matches its data center. |
| **Tuya rejected the request** | Confirm **IoT Core** and **Smart Home Basic Service** are active and authorized, and that the app account is linked to this project. |
| **Cloud push is unavailable** | Confirm **Device Status Notification** is active, the project appears under **Authorized Projects**, the linked account and UID are correct, and the region matches. If just enabled, wait for Tuya to activate it. |
| **No individually shared devices** | Confirm you copied the linked recipient account's UID and that `GET /v1.0/users/{uid}/devices?from=sharing` returns at least one device. Owned devices do not count. |

## Safety

Commands are sent directly through Tuya Cloud. Test physical actuators only
when the surrounding area is clear and the action has been explicitly
authorized.

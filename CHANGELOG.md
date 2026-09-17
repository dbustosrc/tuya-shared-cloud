# Changelog

## 1.3.0 — 2026-09-17

- Add a dedicated **Tuya Shared Cloud** service device for integration-level
  diagnostics.
- Move the existing Cloud push connectivity entity onto that service device and
  add an independent REST polling health entity.
- Add enabled timestamp, delivery-ratio, and REST-correction sensors, plus
  optional detailed counters, polling duration, interval, and shared-device
  count.
- Count the initial REST reconciliation and failed attempts, and record the
  latest attempt, success, failure, and duration without exposing credentials or
  device values.
- Keep diagnostic health entities available while a transport is down so they
  show the failure instead of becoming unavailable.
- Keep device entities available when REST fails but OpenMQ remains connected
  and subscribed.
- Add English and Spanish entity translations and expand standalone coverage.
## 1.2.0 — 2026-09-16

- Correct garage-door control for Tuya category `ckmkzq` to use the standard
  Boolean `switch_1` datapoint instead of the unrelated `door_control_1` enum.
- Add independent per-device options for command inversion, contact-state
  inversion, contact-state trust, and the stateless door trigger button.
- Add a stateless garage-door trigger that remains safe to use when the physical
  contact is stuck or unreliable.
- Stop applying optimistic command values: Tuya push or REST must now confirm a
  state before Home Assistant displays it.
- Keep every raw function exposed, including `switch_1`, `door_control_1`, and
  physically unsupported close commands.
- Move Paho MQTT certificate loading off Home Assistant's event loop.
- Log the normal interval between MQTT connection and subscription
  acknowledgement at debug level instead of warning.
- Document garage-door quirks and the recommended configuration workflow.

## 1.1.0 — 2026-09-16

- Import only devices received through Tuya individual device sharing.
- Add Smart Home OpenMQ cloud push with automatic credential renewal.
- Add a slow REST reconciliation safety net and push-delivery diagnostics.
- Expose writable Boolean, Integer, and Enum datapoints as Home Assistant
  entities while retaining read-only datapoints.
- Add a garage cover entity backed by the physical door-contact state.
- Add HACS metadata, local brand artwork, automated validation, and standalone
  tests.

"""Static packaging tests for Home Assistant diagnostic entities."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "tuya_shared_cloud"


class DiagnosticEntityTests(unittest.TestCase):
    def test_translation_structure_and_placeholders_match(self):
        def keys(value, path=()):
            if isinstance(value, dict):
                return {
                    item
                    for key, child in value.items()
                    for item in keys(child, (*path, key))
                }
            return {path}

        source = json.loads((COMPONENT / "strings.json").read_text())
        for language in ("en", "es"):
            translation = json.loads(
                (COMPONENT / "translations" / f"{language}.json").read_text()
            )
            self.assertEqual(keys(source), keys(translation))
            self.assertIn(
                "{reason}", translation["exceptions"]["command_failed"]["message"]
            )

    def test_release_manifest_and_translations_include_diagnostics(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "1.4.0")

        required_binary_sensors = {"cloud_push", "rest_polling", "doorcontact_state"}
        required_sensors = {
            "last_cloud_message",
            "last_rest_poll",
            "push_delivery_ratio",
            "rest_corrections",
            "cloud_messages",
            "ignored_cloud_messages",
            "rest_polling_runs",
            "rest_polling_failures",
            "rest_polling_duration",
            "rest_polling_interval",
            "shared_devices",
            "door_state_1",
        }
        for relative_path in (
            "strings.json",
            "translations/en.json",
            "translations/es.json",
        ):
            translation = json.loads((COMPONENT / relative_path).read_text())
            self.assertEqual(
                set(translation["entity"]["binary_sensor"]),
                required_binary_sensors,
            )
            self.assertEqual(
                set(translation["entity"]["sensor"]),
                required_sensors,
            )

    def test_diagnostic_device_is_a_service_device(self):
        tree = ast.parse((COMPONENT / "entity.py").read_text(encoding="utf-8"))
        service_references = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "DeviceEntryType"
            and node.attr == "SERVICE"
        ]
        self.assertEqual(len(service_references), 1)


if __name__ == "__main__":
    unittest.main()

"""Static packaging tests for Home Assistant diagnostic entities."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "tuya_shared_cloud"


class DiagnosticEntityTests(unittest.TestCase):
    def test_release_manifest_and_translations_include_diagnostics(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "1.3.0")

        required_binary_sensors = {"cloud_push", "rest_polling"}
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

    def test_rest_metrics_record_attempt_success_and_failure(self):
        source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn("metrics.reconciliation_runs += 1", source)
        self.assertIn("metrics.last_reconciliation_success_at", source)
        self.assertIn("metrics.reconciliation_failures += 1", source)
        self.assertIn("metrics.last_reconciliation_failure_at", source)

    def test_push_keeps_device_entities_available_during_rest_failure(self):
        source = (COMPONENT / "entity.py").read_text(encoding="utf-8")
        self.assertIn("transport_available = super().available or", source)
        self.assertIn("metrics.connected and metrics.subscribed", source)


if __name__ == "__main__":
    unittest.main()

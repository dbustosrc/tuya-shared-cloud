"""Standalone garage-profile tests without Home Assistant installed."""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "tuya_shared_cloud"
PACKAGE = "tuya_shared_cloud_garage_tests"

package = types.ModuleType(PACKAGE)
package.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE] = package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{name}", COMPONENT / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


const = _load("const")
models = _load("models")
garage = _load("garage")


def _device(category: str = "ckmkzq"):
    return models.TuyaSharedDevice(
        device_id="garage-1",
        name="Shared garage",
        category=category,
    )


def _functions(function_type: str = "Boolean"):
    return {
        "garage-1": {
            "switch_1": models.TuyaFunction(
                code="switch_1",
                name="switch 1",
                type=function_type,
                values={},
            )
        }
    }


class GarageProfileTests(unittest.TestCase):
    def test_standard_tuya_mapping(self):
        profile = garage.build_garage_profiles([_device()], _functions(), {})[
            "garage-1"
        ]
        self.assertIs(profile.command_value(const.DOOR_OPEN), True)
        self.assertIs(profile.command_value(const.DOOR_CLOSE), False)
        self.assertIs(profile.contact_is_closed(True), False)
        self.assertIs(profile.contact_is_closed(False), True)

    def test_command_and_contact_inversion_are_independent(self):
        options = {
            const.CONF_GARAGE_DEVICES: {
                "garage-1": {
                    const.CONF_INVERT_COVER_CONTROL: True,
                    const.CONF_INVERT_COVER_STATUS: True,
                    const.CONF_TRUST_COVER_STATUS: True,
                }
            }
        }
        profile = garage.build_garage_profiles([_device()], _functions(), options)[
            "garage-1"
        ]
        self.assertIs(profile.command_value(const.DOOR_OPEN), False)
        self.assertIs(profile.command_value(const.DOOR_CLOSE), True)
        self.assertIs(profile.contact_is_closed(True), True)
        self.assertIs(profile.contact_is_closed(False), False)

    def test_untrusted_contact_is_always_unknown(self):
        options = {
            const.CONF_GARAGE_DEVICES: {
                "garage-1": {const.CONF_TRUST_COVER_STATUS: False}
            }
        }
        profile = garage.build_garage_profiles([_device()], _functions(), options)[
            "garage-1"
        ]
        self.assertIsNone(profile.contact_is_closed(True))
        self.assertIsNone(profile.contact_is_closed(False))

    def test_only_standard_boolean_garage_control_gets_cover_profile(self):
        self.assertEqual(
            garage.build_garage_profiles([_device("switch")], _functions(), {}),
            {},
        )
        self.assertEqual(
            garage.build_garage_profiles(
                [_device()], _functions(function_type="Enum"), {}
            ),
            {},
        )

    def test_command_handler_does_not_write_optimistic_state(self):
        tree = ast.parse((COMPONENT / "coordinator.py").read_text(encoding="utf-8"))
        command_handler = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_send_command"
        )
        calls = [
            node.func.attr
            for node in ast.walk(command_handler)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertNotIn("async_set_updated_data", calls)


if __name__ == "__main__":
    unittest.main()

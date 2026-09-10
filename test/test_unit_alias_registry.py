import json
import tempfile
import unittest
from pathlib import Path

from src.adapters.unit_alias_registry import UnitAliasRegistry, UnitAliasRegistryError
from src.adapters.unit_resolver import UnitResolutionStatus, UnitResolver


class TestUnitAliasRegistry(unittest.TestCase):
    def setUp(self):
        self.units = {
            "P": ["Unit A", "Unit C"],
            "Q": ["20", "40"],
        }

    def test_explicit_alias_resolves_to_existing_canonical_unit(self):
        registry = UnitAliasRegistry({"P": {"H": "Unit A"}}, self.units)
        match = registry.resolve("P", "H")
        self.assertIsNotNone(match)
        self.assertEqual(match.canonical_unit_name, "Unit A")

        result = UnitResolver.from_explicit_alias("H", match.canonical_unit_name)
        self.assertEqual(result.status, UnitResolutionStatus.EXPLICIT_ALIAS)
        self.assertTrue(result.resolved)

    def test_alias_is_property_scoped(self):
        registry = UnitAliasRegistry({"P": {"H": "Unit A"}}, self.units)
        self.assertIsNone(registry.resolve("Q", "H"))

    def test_missing_property_fails_fast(self):
        with self.assertRaises(UnitAliasRegistryError):
            UnitAliasRegistry({"Missing": {"H": "Unit A"}}, self.units)

    def test_missing_target_unit_fails_fast(self):
        with self.assertRaises(UnitAliasRegistryError):
            UnitAliasRegistry({"P": {"F": "Unit F"}}, self.units)

    def test_conflicting_normalized_alias_fails_fast(self):
        with self.assertRaises(UnitAliasRegistryError):
            UnitAliasRegistry({"P": {"APT 03": "Unit A", "#03": "Unit C"}}, self.units)

    def test_duplicate_json_key_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aliases.json"
            path.write_text('{"P": {"H": "Unit A", "H": "Unit C"}}', encoding="utf-8")
            with self.assertRaises(UnitAliasRegistryError):
                UnitAliasRegistry.from_json(path, self.units)

    def test_empty_registry_is_valid(self):
        registry = UnitAliasRegistry({}, self.units)
        self.assertIsNone(registry.resolve("P", "H"))


if __name__ == "__main__":
    unittest.main()

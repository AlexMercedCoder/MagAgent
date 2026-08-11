from __future__ import annotations

from magent.contract_inventory import contract_inventory


def test_contract_inventory_freezes_primary_surfaces() -> None:
    report = contract_inventory(["ask", "system migrate", "gateway configure"])

    assert report["ok"] is True
    assert report["schema"] == "magent.contract-inventory.v1"
    commands = {item["command"]: item["status"] for item in report["cli"]}
    assert commands["ask"] == "stable"
    assert commands["system migrate"] == "stable"
    assert commands["gateway configure"] == "beta"
    assert report["config"]["unknown_keys"] == "preserved"
    assert all(item["status"] == "stable" for item in report["python_imports"])

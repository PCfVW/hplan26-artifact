"""Repository consistency: server pins and launch config agree (NEW)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _servers():
    return json.loads((ROOT / "servers" / "servers.json").read_text(encoding="utf-8"))["servers"]


def test_setup_scripts_pin_the_commits_of_servers_json():
    sh = (ROOT / "servers" / "setup_servers.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "servers" / "setup_servers.ps1").read_text(encoding="utf-8")
    for s in _servers():
        assert len(s["commit"]) == 40
        for text in (sh, ps1):
            assert f'{s["directory"]} {s["repository"]} {s["commit"]}' in text or \
                f'"{s["directory"]}", "{s["repository"]}", "{s["commit"]}"' in text


def test_launch_config_covers_the_eight_servers():
    cfg = json.loads((ROOT / "servers" / "mcp_servers.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(cfg) == {s["name"] for s in _servers()}
    for s in _servers():
        assert cfg[s["name"]]["args"] == [f"${{SERVERS_ROOT}}/{s['directory']}/build/index.js"]


def test_table1_total_is_140():
    assert sum(s["tools_advertised"] for s in _servers()) == 140

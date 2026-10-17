"""`lumen --self-test`: the installer's proof that everything it set up actually works."""

from __future__ import annotations

from gaffer.selftest import run_self_test


def test_the_self_test_boots_a_demo_studio_and_talks_to_it(tmp_path):
    lines: list[str] = []
    ok = run_self_test(report=lines.append, require_web=False)
    assert ok, "\n".join(lines)
    text = "\n".join(lines)
    for part in ("Python", "Bluetooth library", "model table", "server", "WebSocket"):
        assert part in text


def test_a_missing_web_build_is_reported_not_crashed(monkeypatch, tmp_path):
    from gaffer import app as app_module

    monkeypatch.setattr(app_module, "WEB_DIST", tmp_path / "no-dist")
    lines: list[str] = []
    assert run_self_test(report=lines.append, require_web=True) is False
    assert any("web app" in line and "FAIL" in line for line in lines)

"""Regression tests for two MVP-demo bugs found by dogfooding SIL.

- Bug 1: `sil diff` for json+json observations skipped keyword persistence
  even when --keyword was supplied. A deleted id could remain unflagged
  under e.g. `shared_with[].pinned[]` because the structural diff found no
  changes in that subtree.
- Bug 2: `sil diff` for screenshot+screenshot did not expose --ignore-region,
  so dynamic UI elements (timestamps) inflated the differing-pixel ratio.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from app.cli import app
from app.db import session_scope
from app.models import Observation, Scenario


def _make_obs(scenario_id: int, phase: str, observer_type: str, path: Path) -> int:
    with session_scope() as session:
        obs = Observation(
            scenario_id=scenario_id,
            phase=phase,
            observer_type=observer_type,
            artifact_path=str(path),
            note="",
        )
        session.add(obs)
        session.flush()
        return obs.id


def _make_scenario(name: str) -> int:
    with session_scope() as session:
        s = Scenario(name=name, target_service="example.com", hypothesis="x")
        session.add(s)
        session.flush()
        return s.id


def test_json_diff_runs_persistence_when_keywords_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _make_scenario("json_persist_scn")
    deleted_id = "doc_8f7a2bc4-3d11-4e22-9933-aaaa00001111"
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(
        json.dumps(
            {
                "documents": [{"id": deleted_id, "name": "secret"}, {"id": "k"}],
                "shared_with": [{"user": "alice", "pinned": [deleted_id, "k"]}],
            }
        )
    )
    # The deleted document is gone from `documents`, but the id survives in
    # `shared_with[0].pinned[0]`.
    after_path.write_text(
        json.dumps(
            {
                "documents": [{"id": "k"}],
                "shared_with": [{"user": "alice", "pinned": [deleted_id, "k"]}],
            }
        )
    )
    bid = _make_obs(sid, "before", "json", before_path)
    aid = _make_obs(sid, "after", "json", after_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "diff",
            "--before",
            str(bid),
            "--after",
            str(aid),
            "--keyword",
            deleted_id,
            "--no-save",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Persistence findings" in result.stdout
    assert "declared_keyword_persisted" in result.stdout
    assert "needs_review" in result.stdout


def test_screenshot_diff_accepts_ignore_region(tmp_path: Path) -> None:
    sid = _make_scenario("ignore_region_scn")
    before_path = tmp_path / "before.png"
    after_path = tmp_path / "after.png"
    img_a = Image.new("RGB", (40, 40), (255, 255, 255))
    img_a.save(before_path, format="PNG")
    img_b = Image.new("RGB", (40, 40), (255, 255, 255))
    # Change a 10x10 patch (6.25%) so without masking it would be `medium`.
    for x in range(10):
        for y in range(10):
            img_b.putpixel((x, y), (0, 0, 0))
    img_b.save(after_path, format="PNG")
    bid = _make_obs(sid, "before", "screenshot", before_path)
    aid = _make_obs(sid, "after", "screenshot", after_path)

    runner = CliRunner()
    # Without ignore-region: should report a non-zero diff.
    r1 = runner.invoke(
        app,
        ["diff", "--before", str(bid), "--after", str(aid), "--no-save"],
    )
    assert r1.exit_code == 0, r1.stdout
    assert "differ in" in r1.stdout

    # With ignore-region covering the whole changed patch: should be 0%.
    r2 = runner.invoke(
        app,
        [
            "diff",
            "--before",
            str(bid),
            "--after",
            str(aid),
            "--ignore-region",
            "0,0,10,10",
            "--no-save",
        ],
    )
    assert r2.exit_code == 0, r2.stdout
    assert "0.000% of pixels" in r2.stdout


def test_ignore_region_rejects_bad_format(tmp_path: Path) -> None:
    sid = _make_scenario("ignore_bad_scn")
    p = tmp_path / "x.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(p, format="PNG")
    bid = _make_obs(sid, "before", "screenshot", p)
    aid = _make_obs(sid, "after", "screenshot", p)

    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "diff",
            "--before",
            str(bid),
            "--after",
            str(aid),
            "--ignore-region",
            "not,a,region",
            "--no-save",
        ],
    )
    assert r.exit_code != 0

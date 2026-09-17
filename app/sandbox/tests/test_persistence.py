"""The sandbox's own storage (S9): a snapshot that must never be fatal.

The sandbox stands in for a vendor's systems, so this file is *its* storage. It is
off unless configured, and reading or writing it may never take the sandbox down —
a persistence layer that can fail the request it is recording is worse than no
persistence at all.
"""
from __future__ import annotations

import json

from app.sandbox.persistence import SandboxState


def test_disabled_when_no_path_is_configured():
    state = SandboxState(None)
    assert state.enabled is False
    assert state.load() == {"refunds": [], "drafts": []}
    state.save(refunds=[{"id": "r-1"}], drafts=[])  # a no-op, not an error


def test_a_snapshot_round_trips(tmp_path):
    path = str(tmp_path / "state.json")
    SandboxState(path).save(
        refunds=[{"id": "r-0001", "tenant": "acme"}], drafts=[{"id": "d-0001", "tenant": "acme"}]
    )
    assert SandboxState(path).load() == {
        "refunds": [{"id": "r-0001", "tenant": "acme"}],
        "drafts": [{"id": "d-0001", "tenant": "acme"}],
    }


def test_a_missing_snapshot_is_empty_not_an_error(tmp_path):
    assert SandboxState(str(tmp_path / "nope.json")).load() == {"refunds": [], "drafts": []}


def test_a_corrupt_snapshot_is_ignored(tmp_path):
    # A half-written file must not stop the sandbox from starting.
    path = tmp_path / "state.json"
    path.write_text("{ this is not json")
    assert SandboxState(str(path)).load() == {"refunds": [], "drafts": []}


def test_an_unsnapshotable_path_does_not_raise(tmp_path):
    # A directory where the file belongs: the write fails, and is reported rather
    # than raised. A volume that is not mounted should not fail every write.
    path = tmp_path / "state.json"
    path.mkdir()
    SandboxState(str(path)).save(refunds=[{"id": "r-1"}], drafts=[])
    assert path.is_dir()


def test_it_writes_atomically(tmp_path):
    path = str(tmp_path / "state.json")
    state = SandboxState(path)
    state.save(refunds=[{"id": "r-0001"}], drafts=[])
    state.save(refunds=[{"id": "r-0001"}, {"id": "r-0002"}], drafts=[])
    # The temporary file is renamed over the target, so nothing is left beside it
    # and a reader never sees a partial snapshot.
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
    assert len(json.loads((tmp_path / "state.json").read_text())["refunds"]) == 2

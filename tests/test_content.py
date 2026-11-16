from copy import deepcopy

from evidenceloop.content import compute_content_key, content_key


def test_ordinary_content_identity_uses_kind_and_digest():
    first = {"kind": "text", "sha256": "abc"}
    same = {"kind": "text", "sha256": "abc"}
    different = {"kind": "text", "sha256": "def"}

    assert compute_content_key(first) == compute_content_key(same)
    assert compute_content_key(first) != compute_content_key(different)


def test_experiment_content_identity_uses_test_and_logs():
    base = {
        "kind": "experiment",
        "summary": {
            "build_skipped": False,
            "build": {
                "argv": ["make"],
                "exit_code": 0,
                "log_sha256": "build-a",
            },
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 1,
                "timed_out": False,
                "log_sha256": "test-a",
            },
        },
    }
    same = deepcopy(base)
    changed_exit = deepcopy(base)
    changed_exit["summary"]["test"]["exit_code"] = 0
    changed_log = deepcopy(base)
    changed_log["summary"]["test"]["log_sha256"] = "test-b"

    assert compute_content_key(base) == compute_content_key(same)
    assert compute_content_key(base) != compute_content_key(changed_exit)
    assert compute_content_key(base) != compute_content_key(changed_log)


def test_legacy_experiment_without_logs_uses_record_identity():
    first = {
        "kind": "experiment",
        "evidence_id": "E1",
        "source": "/spec-a",
        "summary": {
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 1,
                "timed_out": False,
            }
        },
    }
    second = {
        "kind": "experiment",
        "evidence_id": "E2",
        "source": "/spec-b",
        "summary": {
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 1,
                "timed_out": False,
            }
        },
    }

    assert compute_content_key(first) != compute_content_key(second)


def test_experiment_missing_build_log_uses_record_identity():
    first = {
        "kind": "experiment",
        "evidence_id": "E1",
        "source": "/spec-a",
        "summary": {
            "build_skipped": False,
            "build": {"argv": ["make"], "exit_code": 0},
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 1,
                "timed_out": False,
                "log_sha256": "test-a",
            },
        },
    }
    second = {
        "kind": "experiment",
        "evidence_id": "E2",
        "source": "/spec-b",
        "summary": {
            "build_skipped": False,
            "build": {"argv": ["make"], "exit_code": 0},
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 1,
                "timed_out": False,
                "log_sha256": "test-a",
            },
        },
    }

    assert compute_content_key(first) != compute_content_key(second)


def test_empty_build_object_uses_record_identity():
    first = {
        "kind": "experiment",
        "evidence_id": "E1",
        "source": "/spec-a",
        "summary": {
            "build_skipped": False,
            "build": {},
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 1,
                "timed_out": False,
                "log_sha256": "test-a",
            },
        },
    }
    second = {
        "kind": "experiment",
        "evidence_id": "E2",
        "source": "/spec-b",
        "summary": {
            "build_skipped": False,
            "build": {},
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 1,
                "timed_out": False,
                "log_sha256": "test-a",
            },
        },
    }

    assert compute_content_key(first) != compute_content_key(second)


def test_build_timeout_changes_content_key():
    first = {
        "kind": "experiment",
        "summary": {
            "build_skipped": False,
            "build": {
                "argv": ["make"],
                "exit_code": None,
                "timed_out": True,
                "log_sha256": "build-a",
            },
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 0,
                "timed_out": False,
                "log_sha256": "test-a",
            },
        },
    }
    second = deepcopy(first)
    second["summary"]["build"]["timed_out"] = False

    assert compute_content_key(first) != compute_content_key(second)


def test_build_skipped_changes_content_key():
    base = {
        "kind": "experiment",
        "summary": {
            "build": None,
            "build_skipped": False,
            "test": {
                "test_id": "case",
                "argv": ["run"],
                "exit_code": 0,
                "timed_out": False,
                "log_sha256": "test-a",
            },
        },
    }
    skipped = deepcopy(base)
    skipped["summary"]["build_skipped"] = True

    assert compute_content_key(base) != compute_content_key(skipped)


def test_stored_content_key_wins():
    assert (
        content_key({"kind": "text", "sha256": "abc", "content_key": "stored"})
        == "stored"
    )


def test_legacy_record_without_digest_uses_identity():
    first = {"kind": "text", "sha256": "", "source": "/a", "evidence_id": "E1"}
    same = {"kind": "text", "sha256": "", "source": "/a", "evidence_id": "E1"}
    different = {"kind": "text", "sha256": "", "source": "/a", "evidence_id": "E2"}

    assert compute_content_key(first) == compute_content_key(same)
    assert compute_content_key(first) != compute_content_key(different)

from pathlib import Path

from evidenceloop.parsers import parse_tombstone

FIXTURE = Path(__file__).parent / "fixtures" / "tombstone_sample.log"


def test_signals_and_subprocess_attribution():
    summary = parse_tombstone(FIXTURE)

    assert summary["signal_count"] == 2
    first, second = summary["signal_events"]

    assert first["name"] == "SIGSEGV"
    assert first["pid"] == 100
    assert first["tid"] == 200
    assert first["subprocess"] is False
    assert "example::Exporter::Export" in first["app_frame"]

    assert second["name"] == "SIGABRT"
    assert second["pid"] == 300
    assert second["tid"] == 301
    assert second["subprocess"] is True


def test_build_metadata_is_kept_generically():
    summary = parse_tombstone(FIXTURE)

    assert summary["app"]["version"] == "1.0.0"
    assert summary["app"]["metadata"]["wk_buildRevision"] == "abc123"
    assert summary["app"]["model"] == "TestDevice"
    assert summary["app"]["sdk"] == "36"

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

    assert summary["coverage"]["lines_total"] > 0
    assert (
        summary["coverage"]["frames_total"] >= summary["coverage"]["frames_kept"]
    )
    assert (
        summary["coverage"]["translated_total"]
        >= summary["coverage"]["translated_kept"]
    )


def test_frames_are_bounded(tmp_path):
    lines = ["signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0"]
    lines.extend(
        f"    #{index:02d} pc 00000000000000{index:02d} libfoo.so (foo{index})"
        for index in range(10)
    )
    path = tmp_path / "tombstone.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = parse_tombstone(path)

    assert summary["coverage"]["frames_total"] == 10
    assert summary["coverage"]["frames_kept"] == 8
    assert summary["coverage"]["truncated"] is True


def test_translated_frames_are_not_native_truncation(tmp_path):
    lines = [
        "signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0",
        "translate by crash parser",
        "    #00 pc 0000000000000001 libfoo.so (foo) LINE: 10",
        "    #01 pc 0000000000000002 libbar.so (bar) LINE: 20",
    ]
    path = tmp_path / "tombstone.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = parse_tombstone(path)

    assert summary["coverage"]["frames_total"] == 0
    assert summary["coverage"]["frames_kept"] == 0
    assert summary["coverage"]["translated_total"] == 2
    assert summary["coverage"]["translated_kept"] == 2
    assert summary["coverage"]["truncated"] is False


def test_build_metadata_is_kept_generically():
    summary = parse_tombstone(FIXTURE)

    assert summary["app"]["version"] == "1.0.0"
    assert summary["app"]["metadata"]["wk_buildRevision"] == "abc123"
    assert summary["app"]["model"] == "TestDevice"
    assert summary["app"]["sdk"] == "36"

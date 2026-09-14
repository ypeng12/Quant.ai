"""Protocol and deadline tests; synthetic NTP does not prove market latency."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/probe_l1_clock.py"
spec = importlib.util.spec_from_file_location("probe_l1_clock", SCRIPT)
clock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock)


def response(offset=.24):
    sent = 1_789_395_000.
    request = clock.make_request(int(sent * 1e9))
    packet = bytearray(48)
    packet[0], packet[1] = (4 << 3) | 4, 2
    packet[4:8] = struct.pack("!i", 655)  # ~10ms advertised root delay.
    packet[8:12] = struct.pack("!I", 65)  # ~1ms root dispersion.
    packet[24:32] = request[40:48]
    for position, timestamp in [(32, sent + offset + .01), (40, sent + offset + .012)]:
        packet[position:position+8] = clock.make_request(round(timestamp * 1e9))[40:48]
    return packet, request, sent


def test_offset_sign_rtt_and_uncertainty_preserve_positive_clock_skew():
    packet, request, sent = response()
    result = clock.parse_response(packet, request, sent_wall=sent,
                                  received_wall=sent + .022, elapsed_monotonic=.022)
    assert result["server_minus_host_seconds"] == pytest.approx(.24, abs=1e-6)
    assert result["network_round_trip_seconds"] == pytest.approx(.02, abs=1e-6)
    assert result["estimated_uncertainty_seconds"] >= .015
    low, high = result["estimated_offset_interval_seconds"]
    assert low < .24 < high
    assert "address" not in result


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p.__setitem__(0, (3 << 6) | (4 << 3) | 4), "unsynchronized"),
    (lambda p: p.__setitem__(1, 0), "unsynchronized"),
    (lambda p: p.__setitem__(1, 16), "unsynchronized"),
    (lambda p: p.__setitem__(24, p[24] ^ 1), "originate"),
    (lambda p: p.__setitem__(0, (4 << 3) | 3), "mode"),
    (lambda p: p.__setitem__(slice(40, 48), bytes(8)), "missing_server"),
])
def test_invalid_or_unrelated_packets_are_rejected(mutation, reason):
    packet, request, sent = response()
    mutation(packet)
    with pytest.raises(ValueError, match=reason):
        clock.parse_response(packet, request, sent_wall=sent,
                             received_wall=sent + .022, elapsed_monotonic=.022)


def test_wall_clock_jump_is_reported_and_increases_uncertainty():
    packet, request, sent = response()
    result = clock.parse_response(packet, request, sent_wall=sent,
                                  received_wall=sent + 1.022, elapsed_monotonic=.022)
    assert result["wall_vs_monotonic_elapsed_seconds"] == pytest.approx(1., abs=1e-6)
    assert result["network_round_trip_seconds"] == pytest.approx(.02, abs=1e-6)
    assert result["estimated_uncertainty_seconds"] > 1


def test_read_only_cli_bounds_entire_worker_including_dns(tmp_path):
    # Overall budget expires during spawn, before a long network timeout could
    # govern. The subprocess hard limit also guards regressions in cleanup.
    output = tmp_path / "probe.json"
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(SCRIPT), "--servers", "192.0.2.1",
                             "--timeout", "2", "--max-runtime", "0.001", "--output", str(output)],
                            capture_output=True, text=True, timeout=5)
    import json
    report = json.loads(output.read_text())
    assert result.returncode == 2
    assert time.monotonic() - started < 5
    assert report["status"] == "unavailable"
    assert report["server_results"][0]["reason"] == "bounded_probe_timeout"
    assert report["system_clock_modified"] is False
    assert report["event_timestamps_modified"] is False
    preserved = output.read_bytes()
    repeated = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                              capture_output=True, text=True, timeout=5)
    assert repeated.returncode == 2
    assert output.read_bytes() == preserved

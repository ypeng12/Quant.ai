#!/usr/bin/env python3
"""Read-only, bounded public NTP comparison for L1 timestamp diagnostics.

Never sets the system clock or rewrites an event timestamp. Public UDP NTP is
unauthenticated evidence, not a measurement of broker or exchange latency.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import multiprocessing as mp
from pathlib import Path
import socket
import statistics
import struct
import time

DEFAULT_SERVERS = ("time.apple.com", "time.cloudflare.com", "time.google.com")
NTP_EPOCH = 2_208_988_800
ERA_SECONDS = 2**32


def make_request(wall_time_ns):
    seconds, nanos = divmod(wall_time_ns, 1_000_000_000)
    request = bytearray(48)
    request[0] = (4 << 3) | 3  # NTP v4 client request.
    request[40:48] = struct.pack("!II", (seconds + NTP_EPOCH) % ERA_SECONDS,
                                 nanos * ERA_SECONDS // 1_000_000_000)
    return bytes(request)


def _server_timestamp(packet, position, reference):
    seconds, fraction = struct.unpack("!II", packet[position:position + 8])
    era = round((reference + NTP_EPOCH - seconds) / ERA_SECONDS)
    return seconds + era * ERA_SECONDS + fraction / ERA_SECONDS - NTP_EPOCH


def parse_response(packet, request, *, sent_wall, received_wall, elapsed_monotonic):
    """Validate a server reply and report offset with an uncertainty estimate.

    Offset bounds allow the measured network delay to be asymmetric. They also
    include the server's advertised root dispersion and half root delay; these
    server fields are not independent guarantees of clock accuracy.
    """
    if len(packet) < 48 or len(request) != 48:
        raise ValueError("invalid_packet_length")
    leap, version, mode = packet[0] >> 6, (packet[0] >> 3) & 7, packet[0] & 7
    if mode != 4 or version not in (3, 4):
        raise ValueError("unexpected_ntp_mode_or_version")
    if leap == 3 or not 1 <= packet[1] <= 15:
        raise ValueError("unsynchronized_or_kiss_of_death_server")
    if packet[24:32] != request[40:48]:
        raise ValueError("originate_timestamp_mismatch")
    if packet[32:40] == bytes(8) or packet[40:48] == bytes(8):
        raise ValueError("missing_server_timestamp")
    t2 = _server_timestamp(packet, 32, received_wall)
    t3 = _server_timestamp(packet, 40, received_wall)
    if t3 < t2 or elapsed_monotonic < 0:
        raise ValueError("invalid_server_or_monotonic_order")
    wall_elapsed = received_wall - sent_wall
    discontinuity = wall_elapsed - elapsed_monotonic
    # Monotonic elapsed avoids interpreting local wall-clock adjustments as RTT.
    rtt = elapsed_monotonic - (t3 - t2)
    if rtt < -0.000001:  # Floating-point timestamp resolution, not a latency filter.
        raise ValueError("negative_network_round_trip")
    rtt = max(0.0, rtt)
    root_delay = struct.unpack("!i", packet[4:8])[0] / 65536
    root_dispersion = struct.unpack("!I", packet[8:12])[0] / 65536
    offset = ((t2 - sent_wall) + (t3 - received_wall)) / 2
    uncertainty = rtt / 2 + root_dispersion + max(0., root_delay) / 2 + abs(discontinuity)
    return dict(host_received_at=datetime.fromtimestamp(received_wall, timezone.utc).isoformat(),
                leap_indicator=leap, stratum=packet[1],
                server_minus_host_seconds=offset, network_round_trip_seconds=rtt,
                root_delay_seconds=root_delay, root_dispersion_seconds=root_dispersion,
                wall_vs_monotonic_elapsed_seconds=discontinuity,
                estimated_uncertainty_seconds=uncertainty,
                estimated_offset_interval_seconds=[offset - uncertainty, offset + uncertainty])


def _query(server, timeout):
    # DNS runs inside the killable worker; the parent also bounds DNS delays.
    address = socket.getaddrinfo(server, 123, socket.AF_INET, socket.SOCK_DGRAM)[0][4]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.settimeout(timeout)
        connection.connect(address)
        sent_ns = time.time_ns()
        sent_mono = time.monotonic_ns()
        request = make_request(sent_ns)
        connection.send(request)
        packet = connection.recv(512)
        received_mono = time.monotonic_ns()
        received_ns = time.time_ns()
    return parse_response(packet, request, sent_wall=sent_ns / 1e9,
                          received_wall=received_ns / 1e9,
                          elapsed_monotonic=(received_mono - sent_mono) / 1e9)


def _server_worker(server, samples, timeout, channel):
    results, failures = [], []
    try:
        for _ in range(samples):
            try:
                results.append(_query(server, timeout))
            except (OSError, ValueError, OverflowError) as error:
                # No network addresses, packets, or arbitrary exception text.
                failures.append(type(error).__name__)
        result = dict(server=server, status="complete" if len(results) == samples else "partial" if results else "unavailable",
                      requested_samples=samples, samples=results, failures=failures)
        if results:
            best = min(results, key=lambda row: row["network_round_trip_seconds"])
            result.update(median_server_minus_host_seconds=statistics.median(row["server_minus_host_seconds"] for row in results),
                          lowest_round_trip_sample=best)
        channel.send(result)
    finally:
        channel.close()


def probe(servers=DEFAULT_SERVERS, *, samples=3, timeout=2., max_runtime=10.):
    servers = tuple(dict.fromkeys(servers))
    if not servers or len(servers) > 16 or any(not isinstance(server, str) or not server.strip() for server in servers):
        raise ValueError("Provide between one and sixteen server names")
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 10:
        raise ValueError("samples must be an integer from one to ten")
    if not math.isfinite(timeout) or not 0 < timeout <= 10 or not math.isfinite(max_runtime) or not 0 < max_runtime <= 30:
        raise ValueError("timeout must be in (0,10] and max_runtime in (0,30] seconds")
    started = time.monotonic()
    context = mp.get_context("spawn")
    workers, results = [], []
    try:
        for server in servers:
            reader, writer = context.Pipe(duplex=False)
            process = context.Process(target=_server_worker, args=(server, samples, timeout, writer), daemon=True)
            process.start()
            writer.close()
            workers.append((server, process, reader))
        pending = list(workers)
        while pending and time.monotonic() - started < max_runtime:
            for item in pending[:]:
                server, process, reader = item
                if reader.poll():
                    try:
                        results.append(reader.recv())
                    except EOFError:
                        results.append(dict(server=server, status="unavailable", reason="worker_ended_without_result"))
                    pending.remove(item)
                elif not process.is_alive():
                    results.append(dict(server=server, status="unavailable", reason="worker_ended_without_result"))
                    pending.remove(item)
            if pending:
                time.sleep(min(.02, max(0., max_runtime - (time.monotonic() - started))))
        results.extend(dict(server=server, status="unavailable", reason="bounded_probe_timeout") for server, _, _ in pending)
    finally:
        # Terminate every unfinished worker before joining any, including DNS.
        for _, process, _ in workers:
            if process.is_alive():
                process.terminate()
        for _, process, reader in workers:
            process.join(timeout=.2)
            if process.is_alive():
                process.kill()
                process.join(timeout=.2)
            reader.close()
    results.sort(key=lambda row: servers.index(row["server"]))
    offsets = [row["median_server_minus_host_seconds"] for row in results if "median_server_minus_host_seconds" in row]
    return dict(schema_version=1, sampled_at_host_utc=datetime.now(timezone.utc).isoformat(),
                status="complete" if all(row["status"] == "complete" for row in results) else "partial" if offsets else "unavailable",
                server_results=results, elapsed_seconds=time.monotonic() - started,
                median_across_server_offsets_seconds=statistics.median(offsets) if offsets else None,
                system_clock_modified=False, event_timestamps_modified=False,
                interpretation="Positive offset means public NTP server UTC is ahead of this host wall clock; this is not broker/exchange latency.",
                limitations=["Public UDP NTP responses are unauthenticated.",
                             "Uncertainty uses measured RTT, wall/monotonic disagreement and server-advertised root delay/dispersion; it is an estimate, not a guarantee.",
                             "A current clock offset cannot safely correct previously captured timestamps."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--servers", nargs="+", default=list(DEFAULT_SERVERS))
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=2.)
    parser.add_argument("--max-runtime", type=float, default=10.)
    parser.add_argument("--output", type=Path, help="Write a new JSON file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        if args.output and args.output.exists():
            raise FileExistsError("Output already exists")
        report = probe(args.servers, samples=args.samples, timeout=args.timeout, max_runtime=args.max_runtime)
        serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(serialized)
        print(serialized, end="")
        return 0 if report["status"] == "complete" else 2
    except (ValueError, OSError) as error:
        parser.exit(2, f"Clock probe failed: {type(error).__name__}\n")


if __name__ == "__main__":
    raise SystemExit(main())

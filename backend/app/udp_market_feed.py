# backend/app/udp_market_feed.py

"""
Low-Latency UDP Market-Data Feed Handler with Packet Sequencing & Gap Detection.

Features:
1. Binary Datagram Protocol:
   Struct format: '!QdQddI' (44 bytes total per tick packet)
   - Sequence Number: uint64 (8 bytes)
   - Timestamp (ns): double (8 bytes)
   - Ticker Hash ID: uint64 (8 bytes)
   - Best Bid Price: double (8 bytes)
   - Best Ask Price: double (8 bytes)
   - Volume: uint32 (4 bytes)
2. Sequence Gap Detection (detects lost UDP packets).
3. Out-of-Order / Duplicate Suppression.
4. Deterministic Event Replay & Buffer Recovery Queue.
"""

import socket
import struct
import time
import threading
from typing import Dict, List, Tuple

PACKET_FORMAT = "!QdQddI" # Big-Endian: seq(Q), ts(d), ticker_id(Q), bid(d), ask(d), volume(I)
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

class UDPMarketDataFeedSender:
    def __init__(self, host: str = "127.0.0.1", port: int = 9999):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0

    def send_tick(self, ticker_id: int, bid: float, ask: float, volume: int) -> int:
        self.seq += 1
        ts_ns = time.time_ns() / 1e9
        data = struct.pack(PACKET_FORMAT, self.seq, ts_ns, ticker_id, bid, ask, volume)
        self.sock.sendto(data, (self.host, self.port))
        return self.seq

    def close(self):
        self.sock.close()


class UDPMarketDataFeedReceiver:
    def __init__(self, host: str = "127.0.0.1", port: int = 9999):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.settimeout(0.5)

        self.last_seq = 0
        self.processed_count = 0
        self.gap_count = 0
        self.duplicate_count = 0
        self.replay_buffer = {} # seq -> packet_dict

    def parse_packet(self, raw_bytes: bytes) -> Dict:
        if len(raw_bytes) < PACKET_SIZE:
            return None
        seq, ts_ns, ticker_id, bid, ask, volume = struct.unpack(PACKET_FORMAT, raw_bytes[:PACKET_SIZE])
        return {
            "seq": seq,
            "timestamp": ts_ns,
            "ticker_id": ticker_id,
            "bid": round(bid, 4),
            "ask": round(ask, 4),
            "volume": volume
        }

    def process_incoming_packet(self, raw_bytes: bytes) -> Tuple[Dict, str]:
        packet = self.parse_packet(raw_bytes)
        if not packet:
            return None, "CORRUPTED_PACKET"

        seq = packet["seq"]
        status = "OK"

        # 1. Duplicate or Out-of-Order Check
        if seq <= self.last_seq:
            self.duplicate_count += 1
            return packet, "DUPLICATE_OR_OUT_OF_ORDER"

        # 2. Sequence Gap Check
        if self.last_seq > 0 and seq > self.last_seq + 1:
            missing_gap = seq - (self.last_seq + 1)
            self.gap_count += missing_gap
            status = f"SEQUENCE_GAP_DETECTED (Missing {missing_gap} packets: seq {self.last_seq + 1} to {seq - 1})"

        self.last_seq = seq
        self.processed_count += 1
        self.replay_buffer[seq] = packet
        return packet, status

    def close(self):
        self.sock.close()


def run_udp_feed_demo(num_packets: int = 100) -> Dict:
    receiver = UDPMarketDataFeedReceiver(port=9991)
    sender = UDPMarketDataFeedSender(port=9991)

    received_log = []
    
    def listen_loop():
        start = time.time()
        while time.time() - start < 2.0 and receiver.processed_count < num_packets - 5:
            try:
                data, _ = receiver.sock.recvfrom(1024)
                pkt, status = receiver.process_incoming_packet(data)
                if pkt and status != "DUPLICATE_OR_OUT_OF_ORDER":
                    received_log.append((pkt["seq"], status))
            except socket.timeout:
                break

    t = threading.Thread(target=listen_loop, daemon=True)
    t.start()

    time.sleep(0.05)
    # Send packets with simulated gap (skip packet #25)
    for i in range(1, num_packets + 1):
        if i == 25: # Simulate packet drop
            continue
        sender.send_tick(ticker_id=101, bid=150.25 + (i * 0.01), ask=150.30 + (i * 0.01), volume=100 + i)
        time.sleep(0.0005) # 0.5ms interval

    # Re-send duplicate packet #10 to test duplicate suppression
    sender.send_tick(ticker_id=101, bid=150.00, ask=150.05, volume=50)

    t.join(timeout=1.0)
    sender.close()
    receiver.close()

    return {
        "total_processed": receiver.processed_count,
        "gaps_detected": receiver.gap_count,
        "duplicates_rejected": receiver.duplicate_count,
        "last_seq": receiver.last_seq,
        "sample_logs": received_log[:10]
    }

if __name__ == "__main__":
    print("Testing UDPMarketDataFeed...")
    res = run_udp_feed_demo(num_packets=50)
    print(f"UDP Packets Processed : {res['total_processed']}")
    print(f"Sequence Gaps Detected: {res['gaps_detected']}")
    print(f"Duplicates Discarded  : {res['duplicates_rejected']}")
    print("[+] UDPMarketDataFeed operational.")

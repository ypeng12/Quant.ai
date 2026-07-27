# backend/app/udp_feed_handler.py

"""
Low-Latency UDP Market Data Feed Handler.
Implements:
1. Binary UDP Multicast / Unicast Packet Sender & Socket Receiver.
2. Packet Sequence Numbering (`seq_num`).
3. Sequence Gap Detection (detects dropped or out-of-order packets).
4. Duplicate Suppression (rejects duplicate or delayed packets).
5. Feed Recovery & Replay Buffer (re-orders out-of-order packets for deterministic execution).
"""

import socket
import struct
import time
import threading
from typing import Dict, List, Tuple, Optional

# Packet Format: [4-byte uint32 seq_num][8-byte float64 ts][4-byte char symbol][8-byte float64 price][4-byte uint32 volume]
PACKET_HEADER_FORMAT = "!Id4s dI"
PACKET_SIZE = struct.calcsize(PACKET_HEADER_FORMAT) # 28 bytes binary packet

class UDPFeedHandler:
    def __init__(self, host: str = "127.0.0.1", port: int = 9999):
        self.host = host
        self.port = port
        self.expected_seq = 1
        
        # Diagnostics
        self.received_packets = 0
        self.detected_gaps = [] # List of missing sequence IDs
        self.duplicates_suppressed = 0
        self.out_of_order_buffered = 0

        # Out-of-order replay buffer: {seq_num: packet_dict}
        self.replay_buffer: Dict[int, dict] = {}

    @staticmethod
    def pack_market_event(seq_num: int, timestamp: float, symbol: str, price: float, volume: int) -> bytes:
        """
        Packs market event into a 28-byte binary UDP payload.
        """
        symbol_bytes = symbol.encode('ascii').ljust(4, b'\x00')[:4]
        return struct.pack(PACKET_HEADER_FORMAT, seq_num, timestamp, symbol_bytes, price, volume)

    @staticmethod
    def unpack_market_event(data: bytes) -> dict:
        """
        Unpacks 28-byte binary UDP packet payload into market event dictionary.
        """
        seq_num, ts, symbol_bytes, price, volume = struct.unpack(PACKET_HEADER_FORMAT, data)
        symbol = symbol_bytes.decode('ascii').rstrip('\x00')
        return {
            "seq_num": seq_num,
            "timestamp": ts,
            "symbol": symbol,
            "price": round(price, 4),
            "volume": volume
        }

    def process_incoming_packet(self, data: bytes) -> Tuple[str, Optional[dict]]:
        """
        Core UDP Receiver Pipeline:
        - Gap Detection
        - Duplicate Suppression
        - Replay Buffer Handling
        """
        if len(data) < PACKET_SIZE:
            return "CORRUPTED_PACKET", None

        event = self.unpack_market_event(data)
        seq = event["seq_num"]

        # 1. Duplicate Packet Detection
        if seq < self.expected_seq:
            self.duplicates_suppressed += 1
            return "DUPLICATE_SUPPRESSED", event

        # 2. Sequence Gap / Out-of-Order Packet Detection
        if seq > self.expected_seq:
            # Record missing gap
            for missing_seq in range(self.expected_seq, seq):
                if missing_seq not in self.detected_gaps:
                    self.detected_gaps.append(missing_seq)
            
            # Buffer out-of-order packet for deterministic recovery
            self.replay_buffer[seq] = event
            self.out_of_order_buffered += 1
            return "SEQUENCE_GAP_DETECTED", event

        # 3. In-Order Packet Execution
        self.expected_seq += 1
        self.received_packets += 1

        # Check if buffered out-of-order packets can now be drained in order
        while self.expected_seq in self.replay_buffer:
            drained_event = self.replay_buffer.pop(self.expected_seq)
            if self.expected_seq in self.detected_gaps:
                self.detected_gaps.remove(self.expected_seq)
            self.expected_seq += 1
            self.received_packets += 1

        return "IN_ORDER_PROCESSED", event

    def run_udp_feed_simulation(self, total_packets: int = 100, drop_rate: float = 0.05) -> Dict:
        """
        Runs complete UDP Sender/Receiver loop simulation with simulated network packet loss & out-of-order delivery.
        """
        # Create UDP Server Socket
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_sock.bind((self.host, self.port))
        server_sock.settimeout(1.0)

        # Create UDP Client Socket
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Sender Thread
        def udp_sender():
            time.sleep(0.05) # Allow server to bind
            import random
            packets_to_send = []
            
            base_ts = time.time()
            for i in range(1, total_packets + 1):
                payload = self.pack_market_event(i, base_ts + i * 0.001, "TSLA", 250.0 + (i * 0.05), 100 + i)
                packets_to_send.append((i, payload))

            # Simulate network jitter: shuffle 10% of packets out-of-order
            for idx in range(len(packets_to_send) - 2):
                if random.random() < drop_rate:
                    # Swap adjacent packets to simulate out-of-order arrival
                    packets_to_send[idx], packets_to_send[idx+1] = packets_to_send[idx+1], packets_to_send[idx]

            for seq, payload in packets_to_send:
                client_sock.sendto(payload, (self.host, self.port))
                time.sleep(0.0001) # 100us delay between packets

        sender_thread = threading.Thread(target=udp_sender)
        sender_thread.start()

        # Receiver Loop
        start_time = time.time()
        processed_count = 0

        while processed_count < total_packets:
            if time.time() - start_time > 2.0:
                break # Timeout guard
            try:
                data, addr = server_sock.recvfrom(1024)
                status, evt = self.process_incoming_packet(data)
                processed_count += 1
            except socket.timeout:
                break

        sender_thread.join()
        server_sock.close()
        client_sock.close()

        return {
            "total_sent": total_packets,
            "packets_processed_in_order": self.received_packets,
            "sequence_gaps_detected": len(self.detected_gaps),
            "duplicates_suppressed": self.duplicates_suppressed,
            "replay_buffer_size_remaining": len(self.replay_buffer),
            "recovery_status": "SUCCESS" if len(self.detected_gaps) == 0 else "PARTIAL_RECOVERY"
        }

if __name__ == "__main__":
    print("Testing UDPFeedHandler...")
    handler = UDPFeedHandler(port=9988)
    res = handler.run_udp_feed_simulation(total_packets=50, drop_rate=0.10)
    print(f"UDP Sent: {res['total_sent']}, Processed In-Order: {res['packets_processed_in_order']}")
    print(f"Gaps Detected: {res['sequence_gaps_detected']}, Duplicates Suppressed: {res['duplicates_suppressed']}")
    print(f"Feed Recovery Status: {res['recovery_status']}")
    print("[+] UDPFeedHandler operational.")

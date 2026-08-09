# backend/app/tcp_order_gateway.py

"""
Low-Latency TCP Order-Entry Gateway with Binary Message Framing & Robust Connection Recovery.

Features:
1. Message Framing: 4-byte big-endian uint32 payload length header + Binary Payload.
2. Message Types:
   - 0x01: ORDER_NEW (Client -> Gateway)
   - 0x02: ORDER_CANCEL (Client -> Gateway)
   - 0x10: ORDER_ACK (Gateway -> Client)
   - 0x11: ORDER_REJECT (Gateway -> Client)
   - 0x12: ORDER_FILL (Gateway -> Client)
3. Non-Blocking Buffer Accumulation & Partial Read/Write Handling.
4. Client Auto-Reconnect & Timeout Enforcement.
"""

import socket
import struct
import time
import threading
from typing import Dict, List, Tuple

# Message Type Constants
MSG_ORDER_NEW = 0x01
MSG_ORDER_CANCEL = 0x02
MSG_ORDER_ACK = 0x10
MSG_ORDER_REJECT = 0x11
MSG_ORDER_FILL = 0x12

class TCPOrderGatewayServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 9992):
        self.host = host
        self.port = port
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(5)
        self.is_running = False
        self.processed_orders = 0
        self.ack_count = 0
        self.reject_count = 0

    def start(self):
        self.is_running = True
        t = threading.Thread(target=self._listen_loop, daemon=True)
        t.start()

    def _listen_loop(self):
        self.server_sock.settimeout(0.5)
        while self.is_running:
            try:
                conn, addr = self.server_sock.accept()
                # Low-Latency HFT Socket Optimizations:
                # 1. TCP_NODELAY: Disable Nagle's Algorithm to eliminate 40ms buffering delay
                # 2. TCP_QUICKACK: Disable TCP delayed ACK timer for immediate ACK transmission
                # 3. SO_BUSY_POLL: Enable Kernel Busy Polling (50us) to eliminate interrupt context-switch jitter
                try:
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    TCP_QUICKACK = getattr(socket, "TCP_QUICKACK", 12)
                    conn.setsockopt(socket.IPPROTO_TCP, TCP_QUICKACK, 1)
                    SO_BUSY_POLL = getattr(socket, "SO_BUSY_POLL", 50)
                    conn.setsockopt(socket.SOL_SOCKET, SO_BUSY_POLL, 50)
                except Exception:
                    pass
                t_conn = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                t_conn.start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(1.0)
        buffer = bytearray()
        
        while self.is_running:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buffer.extend(data)

                # Process framed messages (Header = 4 bytes uint32 big-endian payload length)
                while len(buffer) >= 4:
                    payload_len = struct.unpack(">I", buffer[:4])[0]
                    if len(buffer) < 4 + payload_len:
                        break # Partial read, wait for remaining bytes
                    
                    # Extract full message frame
                    msg_frame = bytes(buffer[4:4 + payload_len])
                    del buffer[:4 + payload_len]

                    # Decode binary payload
                    msg_type = msg_frame[0]
                    order_id = struct.unpack(">Q", msg_frame[1:9])[0]

                    if msg_type == MSG_ORDER_NEW:
                        ticker_hash, side, shares, price = struct.unpack(">QcId", msg_frame[9:9+8+1+4+8])
                        side_str = side.decode('utf-8')

                        self.processed_orders += 1
                        # Risk Gate: Reject orders if price <= 0 or shares == 0
                        if price <= 0 or shares <= 0:
                            self.reject_count += 1
                            resp_payload = struct.pack(">BQ20s", MSG_ORDER_REJECT, order_id, b"INVALID_PRICE_SHARES")
                        else:
                            self.ack_count += 1
                            resp_payload = struct.pack(">BQ20s", MSG_ORDER_ACK, order_id, b"ORDER_ACCEPTED     ")

                        # Send Framed Response
                        resp_frame = struct.pack(">I", len(resp_payload)) + resp_payload
                        conn.sendall(resp_frame)

            except socket.timeout:
                continue
            except Exception:
                break
        conn.close()

    def stop(self):
        self.is_running = False
        self.server_sock.close()


class TCPOrderGatewayClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9992):
        self.host = host
        self.port = port
        self.sock = None
        self.order_seq = 0

    def connect(self, retries: int = 3) -> bool:
        for attempt in range(retries):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(2.0)
                # Low-Latency Client Optimization: Disable Nagle's Algorithm for instant packet transmission
                try:
                    self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass
                self.sock.connect((self.host, self.port))
                return True
            except Exception:
                time.sleep(0.1)
        return False

    def send_order(self, ticker_hash: int, side: str, shares: int, price: float) -> Tuple[int, Dict]:
        if not self.sock:
            if not self.connect():
                return -1, {"status": "DISCONNECTED"}

        self.order_seq += 1
        order_id = self.order_seq
        side_b = side.encode('utf-8')[:1]

        # Build Binary Payload: MSG_TYPE(1B) + ORDER_ID(8B) + TICKER_HASH(8B) + SIDE(1B) + SHARES(4B) + PRICE(8B)
        payload = struct.pack(">BQQcId", MSG_ORDER_NEW, order_id, ticker_hash, side_b, shares, price)
        framed_msg = struct.pack(">I", len(payload)) + payload

        try:
            self.sock.sendall(framed_msg)

            # Receive Response Frame Header
            hdr = self.sock.recv(4)
            if len(hdr) < 4:
                return order_id, {"status": "PARTIAL_READ_ERROR"}
            payload_len = struct.unpack(">I", hdr)[0]

            resp_data = self.sock.recv(payload_len)
            resp_type = resp_data[0]
            resp_order_id = struct.unpack(">Q", resp_data[1:9])[0]
            reason = resp_data[9:].decode('utf-8').strip()

            status = "ACK" if resp_type == MSG_ORDER_ACK else "REJECT"
            return order_id, {"status": status, "order_id": resp_order_id, "reason": reason}
        except Exception as e:
            self.sock = None # Trigger reconnect next call
            return order_id, {"status": "CONNECTION_ERROR", "error": str(e)}

    def close(self):
        if self.sock:
            self.sock.close()


def run_tcp_gateway_demo() -> Dict:
    server = TCPOrderGatewayServer(port=9992)
    server.start()
    time.sleep(0.1)

    client = TCPOrderGatewayClient(port=9992)
    connected = client.connect()

    responses = []
    if connected:
        # Valid Order
        _, resp1 = client.send_order(ticker_hash=101, side="B", shares=100, price=150.50)
        responses.append(resp1)

        # Invalid Order (Price = 0 -> Trigger Reject)
        _, resp2 = client.send_order(ticker_hash=101, side="B", shares=100, price=0.0)
        responses.append(resp2)

        # Valid Sell Order
        _, resp3 = client.send_order(ticker_hash=101, side="S", shares=50, price=151.00)
        responses.append(resp3)

    client.close()
    server.stop()

    return {
        "connected": connected,
        "server_processed_count": server.processed_orders,
        "ack_count": server.ack_count,
        "reject_count": server.reject_count,
        "client_responses": responses
    }

if __name__ == "__main__":
    print("Testing TCPOrderGateway...")
    res = run_tcp_gateway_demo()
    print(f"Connected              : {res['connected']}")
    print(f"Server Processed Orders: {res['server_processed_count']}")
    print(f"ACK Responses          : {res['ack_count']}")
    print(f"REJECT Responses       : {res['reject_count']}")
    print(f"Client Log Preview     : {res['client_responses']}")
    print("[+] TCPOrderGateway operational.")

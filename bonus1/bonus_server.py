import argparse
import json
import logging
import socket
import socketserver
import threading
import time
import uuid
from datetime import datetime, timezone

from bank_state import BankState
from etcd_store import EtcdStore
from leadership import Leadership, RENEW_SECONDS


def log_event(event, **fields):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    logging.info(json.dumps(entry))


def reject_constant(value):
    raise ValueError("Invalid JSON number")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        started = time.perf_counter()
        trace_id = uuid.uuid4().hex
        request = None
        self.request.settimeout(10)

        try:
            raw = self.rfile.readline(4097)

            if not raw:
                return

            request = raw.decode("utf-8", errors="replace")

            log_event(
                "received",
                trace_id=trace_id,
                client_ip=self.client_address[0],
                request=request,
            )

            if len(raw) > 4096 or not raw.endswith(b"\n"):
                raise ValueError("Request must fit in 4096 bytes and end with newline")

            try:
                request = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=reject_constant,
                )
            except (ValueError, UnicodeDecodeError):
                raise ValueError("Malformed JSON")

            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")

            if not self.server.ready.is_set():
                response = {
                    "status": "error",
                    "message": "Not an available primary; retry another server",
                    "retryable": True,
                }
            else:
                response = self.server.bank.execute(request)

        except ValueError as error:
            response = {
                "status": "error",
                "message": str(error),
                "retryable": False,
            }

        except socket.timeout:
            response = {
                "status": "error",
                "message": "Request timed out",
                "retryable": True,
            }

        except RuntimeError as error:
            response = {
                "status": "error",
                "message": str(error),
                "retryable": True,
            }

        except Exception:
            logging.exception("Unexpected handler error")
            response = {
                "status": "error",
                "message": "Internal server error",
                "retryable": True,
            }

        response.setdefault(
            "request_id",
            request.get("request_id") if isinstance(request, dict) else None,
        )
        response["server"] = self.server.node_name

        log_event(
            "result",
            trace_id=trace_id,
            client_ip=self.client_address[0],
            action=request.get("action") if isinstance(request, dict) else None,
            account=request.get("account") if isinstance(request, dict) else None,
            request_id=response["request_id"],
            response=response,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

        # Demonstration: the transaction is committed, but no reply yet.
        if (
            response["status"] == "success"
            and isinstance(request, dict)
            and request.get("action") in ("deposit", "withdraw")
            and self.server.reply_delay > 0
        ):
            log_event(
                "reply_delayed",
                request_id=response["request_id"],
                seconds=self.server.reply_delay,
            )
            time.sleep(self.server.reply_delay)

        try:
            self.request.sendall(
                (json.dumps(response) + "\n").encode("utf-8")
            )
        except OSError:
            log_event("reply_failed", trace_id=trace_id)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, name, bank, ready, max_clients, reply_delay):
        self.node_name = name
        self.bank = bank
        self.ready = ready
        self.reply_delay = reply_delay
        self.slots = threading.BoundedSemaphore(max_clients)
        super().__init__(address, Handler)

    def process_request(self, connection, address):
        if not self.slots.acquire(blocking=False):
            response = {
                "status": "error",
                "message": "Server busy",
                "retryable": True,
                "server": self.node_name,
            }
            try:
                connection.settimeout(1)
                connection.sendall(
                    (json.dumps(response) + "\n").encode("utf-8")
                )
            except OSError:
                pass
            finally:
                log_event(
                    "busy",
                    client_ip=address[0],
                    response=response,
                )
                self.shutdown_request(connection)
            return

        try:
            super().process_request(connection, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, connection, address):
        try:
            super().process_request_thread(connection, address)
        finally:
            self.slots.release()


def election_loop(leadership, bank, ready, stop):
    while not stop.is_set():
        try:
            if leadership.tick():
                if not ready.is_set():
                    bank.initialize()
                    ready.set()
                    log_event("primary_ready", server=leadership.name)
            else:
                ready.clear()
        except Exception as error:
            ready.clear()
            leadership.token = None
            log_event("primary_unavailable", message=str(error))

        stop.wait(RENEW_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Bonus banking server")
    parser.add_argument("--name", required=True, choices=["A", "B"])
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--max-clients", type=int, default=20)
    parser.add_argument("--endpoint", default="http://127.0.0.1:2379")
    parser.add_argument("--reply-delay", type=float, default=0)
    args = parser.parse_args()

    if args.max_clients < 1 or args.reply_delay < 0:
        parser.error("Invalid client limit or reply delay")

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            logging.FileHandler(f"bonus-{args.name}.log"),
            logging.StreamHandler(),
        ],
    )

    store = EtcdStore(args.endpoint)
    leadership = Leadership(store, args.name)
    bank = BankState(store, leadership)
    ready = threading.Event()
    stop = threading.Event()

    with Server(
        ("0.0.0.0", args.port),
        args.name,
        bank,
        ready,
        args.max_clients,
        args.reply_delay,
    ) as server:
        worker = threading.Thread(
            target=election_loop,
            args=(leadership, bank, ready, stop),
            daemon=True,
        )
        worker.start()

        print(f"Banking server {args.name} listening on port {args.port}", flush=True)

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping banking server", flush=True)
        finally:
            ready.clear()
            stop.set()


if __name__ == "__main__":
    main()

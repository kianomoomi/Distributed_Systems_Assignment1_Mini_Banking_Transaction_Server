import argparse
import json
import logging
import socket
import socketserver
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

from database import bank_operation, initialize_database


def log_exchange(request_id, ip, request, response, started, delivery):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "client_ip": ip,
        "action": request.get("action") if isinstance(request, dict) else None,
        "account": request.get("account") if isinstance(request, dict) else None,
        "request": request,
        "response": response,
        "result": response["status"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "delivery": delivery,
    }
    logging.info(json.dumps(entry, ensure_ascii=True))


def send_response(connection, response):
    message = json.dumps(response) + "\n"
    connection.sendall(message.encode("utf-8"))


def reject_json_constant(value):
    # Python otherwise accepts nonstandard JSON values such as NaN.
    raise ValueError("Invalid JSON number")


class BankHandler(socketserver.StreamRequestHandler):
    def handle(self):
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        request = None
        delivery = "failed"

        self.request.settimeout(10)

        try:
            # Requests must end with a newline and fit in 4096 bytes.
            raw = self.rfile.readline(4097)

            # A connection closed without sending a request.
            if not raw:
                return

            request = raw.decode("utf-8", errors="replace")

            if len(raw) > 4096:
                raise ValueError("Request exceeds 4096 bytes")

            if not raw.endswith(b"\n"):
                raise ValueError("Request must end with a newline")

            try:
                request = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=reject_json_constant,
                )
            except (ValueError, UnicodeDecodeError):
                raise ValueError("Malformed JSON")

            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")

            if "action" not in request or "account" not in request:
                raise ValueError("Missing action or account")

            action = request["action"]
            account = request["account"]

            if action not in ("balance", "deposit", "withdraw"):
                raise ValueError("Unsupported action")

            if action != "balance" and "amount" not in request:
                raise ValueError("Missing amount")

            fail = request.get("fail_before_commit", False)

            if type(fail) is not bool:
                raise ValueError("fail_before_commit must be true or false")

            if fail and not self.server.demo_mode:
                raise ValueError("Failure simulation requires --demo-mode")

            balance = bank_operation(
                action,
                account,
                request.get("amount"),
                fail_before_commit=fail,
            )

            response = {
                "status": "success",
                "account": account,
                "balance": balance,
                "unit": "cents",
            }

        except ValueError as error:
            response = {"status": "error", "message": str(error)}

        except socket.timeout:
            response = {"status": "error", "message": "Request timed out"}

        except sqlite3.Error:
            response = {
                "status": "error",
                "message": "Database operation failed; no success confirmed",
            }

        except RuntimeError:
            response = {
                "status": "error",
                "message": "Simulated failure; transaction rolled back",
            }

        except Exception:
            logging.exception("Unexpected request handler error")
            response = {"status": "error", "message": "Internal server error"}

        response["request_id"] = request_id

        try:
            send_response(self.request, response)
            delivery = "sent"
        except OSError:
            # A disconnected client must not crash the server.
            pass
        finally:
            log_exchange(
                request_id,
                self.client_address[0],
                request,
                response,
                started,
                delivery,
            )


class BankServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = False

    def __init__(self, address, max_clients, demo_mode):
        self.slots = threading.BoundedSemaphore(max_clients)
        self.demo_mode = demo_mode
        super().__init__(address, BankHandler)

    def process_request(self, connection, address):
        if not self.slots.acquire(blocking=False):
            started = time.perf_counter()
            request_id = uuid.uuid4().hex
            response = {
                "status": "error",
                "message": "Server busy; maximum clients reached",
                "request_id": request_id,
            }
            delivery = "failed"

            try:
                connection.settimeout(2)
                send_response(connection, response)
                delivery = "sent"
            except OSError:
                pass
            finally:
                log_exchange(
                    request_id, address[0], None,
                    response, started, delivery,
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


def main():
    parser = argparse.ArgumentParser(description="Mini banking TCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--max-clients", type=int, default=20)
    parser.add_argument("--demo-mode", action="store_true")
    args = parser.parse_args()

    if args.max_clients < 1:
        parser.error("--max-clients must be at least 1")

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            logging.FileHandler("bank.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    initialize_database()

    with BankServer(
        (args.host, args.port),
        args.max_clients,
        args.demo_mode,
    ) as server:
        print(
            f"Listening on {args.host}:{args.port} "
            f"| max clients: {args.max_clients} "
            f"| demo mode: {args.demo_mode}",
            flush=True,
        )

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server...", flush=True)


if __name__ == "__main__":
    main()

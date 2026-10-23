import argparse
import json
import socket
import sys
import time
import uuid


class FailoverClient:
    def __init__(self):
        self.servers = [
            ("A", "10.211.55.4"),
            ("B", "10.211.55.5"),
        ]
        self.preferred = 0

    def call(self, action, account, amount=None, request_id=None):
        request = {
            "request_id": request_id or uuid.uuid4().hex,
            "action": action,
            "account": account,
        }

        if amount is not None:
            request["amount"] = amount

        # Construct this once: every retry sends the SAME operation ID.
        message = (json.dumps(request) + "\n").encode("utf-8")
        deadline = time.monotonic() + 60

        print(
            f"Sending {action}, request_id={request['request_id']}",
            file=sys.stderr,
            flush=True,
        )

        while time.monotonic() < deadline:
            index = self.preferred
            name, host = self.servers[index]
            timeout = min(4, deadline - time.monotonic())

            if timeout <= 0:
                break

            try:
                with socket.create_connection(
                    (host, 5001), timeout=timeout
                ) as connection:
                    connection.settimeout(timeout)
                    connection.sendall(message)

                    with connection.makefile("rb") as reader:
                        line = reader.readline(65537)

                if (
                    not line
                    or len(line) > 65536
                    or not line.endswith(b"\n")
                ):
                    raise ValueError("Invalid or missing response")

                response = json.loads(line.decode("utf-8"))

                if not isinstance(response, dict):
                    raise ValueError("Response must be an object")

                if response.get("retryable") is True:
                    print(
                        f"{name}: {response.get('message')}; retrying",
                        file=sys.stderr,
                        flush=True,
                    )

                else:
                    if response.get("request_id") != request["request_id"]:
                        raise ValueError("Response request ID does not match")

                    if response.get("status") not in ("success", "error"):
                        raise ValueError("Invalid response status")

                    return response

            except (OSError, ValueError) as error:
                print(
                    f"{name}: {error}; retrying the same request ID",
                    file=sys.stderr,
                    flush=True,
                )

            self.preferred = 1 - index
            time.sleep(0.5)

        raise RuntimeError(
            "No confirmed result within 60 seconds. Outcome is uncertain. "
            f"Retry the SAME operation with request_id={request['request_id']}"
        )


def main():
    parser = argparse.ArgumentParser(description="Failover banking client")
    parser.add_argument("action", choices=["balance", "deposit", "withdraw"])
    parser.add_argument("account")
    parser.add_argument("amount", type=int, nargs="?")
    parser.add_argument("--request-id")
    args = parser.parse_args()

    if args.action != "balance" and args.amount is None:
        parser.error("Deposit and withdraw require an amount in cents")

    client = FailoverClient()

    try:
        response = client.call(
            args.action,
            args.account,
            args.amount,
            args.request_id,
        )
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)

    print(json.dumps(response, indent=2))

    if response["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

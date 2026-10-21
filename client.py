import argparse
import json
import socket


def send_raw(host, port, message):
    """Send bytes and read one newline-terminated JSON response."""
    with socket.create_connection((host, port), timeout=40) as connection:
        connection.settimeout(40)
        connection.sendall(message)

        with connection.makefile("rb") as reader:
            line = reader.readline(65537)

        if not line:
            raise ConnectionError("Server closed without a response")

        if len(line) > 65536 or not line.endswith(b"\n"):
            raise ConnectionError("Invalid or oversized server response")

        return json.loads(line.decode("utf-8"))


def send_request(host, port, request):
    message = (json.dumps(request) + "\n").encode("utf-8")
    return send_raw(host, port, message)


def main():
    parser = argparse.ArgumentParser(description="Mini banking client")
    parser.add_argument("action", choices=["balance", "deposit", "withdraw"])
    parser.add_argument("account")
    parser.add_argument("amount", type=int, nargs="?")
    parser.add_argument("--host", default="10.37.129.4")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--fail-before-commit", action="store_true")
    args = parser.parse_args()

    if args.action != "balance" and args.amount is None:
        parser.error("deposit and withdraw require an amount in cents")

    request = {
        "action": args.action,
        "account": args.account,
    }

    if args.amount is not None:
        request["amount"] = args.amount

    if args.fail_before_commit:
        request["fail_before_commit"] = True

    try:
        response = send_request(args.host, args.port, request)
    except (OSError, ValueError) as error:
        print(f"Connection or response error: {error}")
        print("The outcome may be unknown; do not automatically repeat a payment.")
        raise SystemExit(1)

    print(json.dumps(response, indent=2))

    if response["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

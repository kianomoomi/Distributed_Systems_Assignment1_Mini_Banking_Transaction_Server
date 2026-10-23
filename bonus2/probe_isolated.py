"""Run on the client while Server A is isolated."""

import json
import socket
import uuid


def main():
    request = {
        "request_id": uuid.uuid4().hex,
        "action": "balance",
        "account": "A1001",
    }

    try:
        with socket.create_connection(
            ("10.211.55.4", 5001), timeout=5
        ) as connection:
            connection.settimeout(12)
            connection.sendall(
                (json.dumps(request) + "\n").encode("utf-8")
            )

            with connection.makefile("rb") as reader:
                line = reader.readline(65537)

        if not line or len(line) > 65536 or not line.endswith(b"\n"):
            raise ValueError("Missing or invalid response")

        response = json.loads(line.decode("utf-8"))
        print(json.dumps(response, indent=2))

        if (
            response.get("request_id") != request["request_id"]
            or response.get("server") != "A"
            or response.get("status") != "error"
            or response.get("retryable") is not True
        ):
            raise ValueError("Unexpected response from isolated A")

        print("PASS: isolated A is reachable and refuses the operation")

    except (OSError, ValueError) as error:
        print(f"Probe did not establish the expected refusal: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

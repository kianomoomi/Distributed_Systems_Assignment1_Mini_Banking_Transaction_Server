import argparse
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from client import send_raw, send_request


def run_tests(host, port):
    def request(data):
        return send_request(host, port, data)

    def balance(account):
        response = request({"action": "balance", "account": account})
        assert response["status"] == "success", response
        return response["balance"]

    def expect_error(label, data, expected_message):
        response = request(data)
        assert response["status"] == "error", response
        assert expected_message in response["message"], response
        print(f"PASS: {label}")

    # Every rejected operation below must leave A1001 unchanged.
    before_errors = balance("A1001")

    expect_error(
        "unknown account",
        {"action": "balance", "account": "Z9999"},
        "Unknown account",
    )

    # Larger than the available balance, but within the supported limit.
    current = balance("A1001")
    assert current < 1_000_000_000_000, "Use an account below the balance limit"

    expect_error(
        "insufficient funds",
        {
            "action": "withdraw",
            "account": "A1001",
            "amount": current + 1,
        },
        "Insufficient funds",
    )

    for amount in (-50, 0, "abc", True, 1.5):
        expect_error(
            f"invalid amount {amount!r}",
            {"action": "deposit", "account": "A1001", "amount": amount},
            "Amount must be",
        )

    expect_error(
        "unsupported action",
        {"action": "transfer", "account": "A1001", "amount": 100},
        "Unsupported action",
    )

    expect_error(
        "missing amount",
        {"action": "withdraw", "account": "A1001"},
        "Missing amount",
    )

    expect_error(
        "missing account",
        {"action": "balance"},
        "Missing action or account",
    )

    for message in (b'{"action":\n', b"\xff\xfe\n"):
        response = send_raw(host, port, message)
        assert response["status"] == "error", response
        assert response["message"] == "Malformed JSON", response
        print("PASS: malformed request")

    assert balance("A1001") == before_errors
    print("PASS: rejected requests left the balance unchanged")

    # The SQL UPDATE executes, then an exception occurs before COMMIT.
    before_failure = balance("A1001")

    expect_error(
        "failure halfway through a transaction",
        {
            "action": "deposit",
            "account": "A1001",
            "amount": 12345,
            "fail_before_commit": True,
        },
        "transaction rolled back",
    )

    assert balance("A1001") == before_failure
    print("PASS: rollback preserved the original balance")

    # Ten connections begin their withdrawals together.
    workers = 10
    barrier = Barrier(workers)
    original = balance("A1003")

    # Add exactly the amount that the concurrent test will withdraw.
    response = request({
        "action": "deposit",
        "account": "A1003",
        "amount": workers * 100,
    })
    assert response["status"] == "success", response

    def withdraw(number):
        barrier.wait(timeout=15)
        return request({
            "action": "withdraw",
            "account": "A1003",
            "amount": 100,
        })

    with ThreadPoolExecutor(max_workers=workers) as pool:
        responses = list(pool.map(withdraw, range(workers)))

    for response in responses:
        assert response["status"] == "success", response

    final = balance("A1003")
    print(f"Concurrent withdrawals: {workers}")
    print(f"Expected final balance: {original}")
    print(f"Actual final balance:   {final}")
    assert final == original, "Incorrect concurrent result"
    print("PASS: concurrent withdrawals produced the correct balance")

    print("\nAll network tests passed")


def main():
    parser = argparse.ArgumentParser(description="Banking network tests")
    parser.add_argument("--host", default="10.37.129.4")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    run_tests(args.host, args.port)


if __name__ == "__main__":
    main()

import time

from bonus_client import FailoverClient

client = FailoverClient()
account = "A1001"


def successful(action, amount=None):
    response = client.call(action, account, amount)

    if response["status"] != "success":
        raise RuntimeError(f"Operation rejected: {response}")

    return response


start = successful("balance")["balance"]
expected = start

print(f"Starting balance: {start}", flush=True)
print("Run this test without other clients modifying A1001.", flush=True)

for number in range(1, 31):
    deposit = successful("deposit", 100)
    expected += 100

    print(
        f"{number:02d} deposit 100 | server={deposit['server']} "
        f"| balance={deposit['balance']}",
        flush=True,
    )
    assert deposit["balance"] == expected
    time.sleep(1)

    withdrawal = successful("withdraw", 40)
    expected -= 40

    print(
        f"{number:02d} withdraw 40 | server={withdrawal['server']} "
        f"| balance={withdrawal['balance']}",
        flush=True,
    )
    assert withdrawal["balance"] == expected
    time.sleep(1)

final = successful("balance")["balance"]

print(f"\nStarting balance: {start}", flush=True)
print(f"Expected balance: {expected}", flush=True)
print(f"Actual balance:   {final}", flush=True)

assert final == expected
assert final == start + 1800

print("PASS: workload completed with the correct balance", flush=True)

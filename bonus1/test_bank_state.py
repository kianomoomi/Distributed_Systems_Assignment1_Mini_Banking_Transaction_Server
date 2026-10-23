import json
import uuid

from bank_state import BankState
from etcd_store import EtcdStore
from leadership import Leadership

store = EtcdStore("http://127.0.0.1:2379")
leadership = Leadership(store, "B")

if not leadership.tick():
    raise RuntimeError(
        "Another primary still owns the role. Stop its leadership process "
        "and wait at least 12 seconds before running this test again."
    )

bank = BankState(store, leadership)
bank.initialize()


def run(action, account="A1001", amount=None, request_id=None):
    # Renew ownership while running this short component test.
    if not leadership.tick():
        raise RuntimeError("Test lost primary ownership")

    request = {
        "request_id": request_id or uuid.uuid4().hex,
        "action": action,
        "account": account,
    }

    if amount is not None:
        request["amount"] = amount

    return bank.execute(request)


before = run("balance")
assert before["status"] == "success", before

deposit_id = uuid.uuid4().hex

first = run("deposit", amount=200, request_id=deposit_id)
assert first["status"] == "success", first

retry = run("deposit", amount=200, request_id=deposit_id)
assert first == retry

after = run("balance")
assert after["balance"] == before["balance"] + 200

print("PASS: deposit applied exactly once")
print(json.dumps(first, indent=2))

try:
    run("deposit", amount=999, request_id=deposit_id)
except ValueError as error:
    print("PASS: conflicting request ID rejected:", error)
else:
    raise AssertionError("Conflicting request ID was accepted")

# Undo the test deposit using a NEW operation ID.
restored = run("withdraw", amount=200)
assert restored["status"] == "success", restored
assert restored["balance"] == before["balance"]

print("PASS: original balance restored")
print("All banking component tests passed")

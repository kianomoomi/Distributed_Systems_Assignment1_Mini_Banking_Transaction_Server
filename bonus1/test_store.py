import json

from etcd_store import EtcdStore

store = EtcdStore("http://127.0.0.1:2379")

# These are demonstration keys, separate from future banking accounts.
ACCOUNT = "/bonus-demo/account"
REQUEST = "/bonus-demo/requests/deposit-001"
AMOUNT = 200

# Initialize once. Running this script again will not reset the balance.
store.transaction(
    [store.missing(ACCOUNT)],
    [store.put(ACCOUNT, "1000")],
)


def deposit_once():
    for _ in range(20):
        saved = store.get(REQUEST)

        if saved is not None:
            print("Previously completed: returning saved result")
            return json.loads(saved["value"])

        account = store.get(ACCOUNT)

        if account is None:
            raise RuntimeError("Demo account is missing")

        new_balance = int(account["value"]) + AMOUNT

        result = {
            "status": "success",
            "request_id": "deposit-001",
            "balance": new_balance,
        }

        committed = store.transaction(
            [
                store.missing(REQUEST),
                store.unchanged(ACCOUNT, account["revision"]),
            ],
            [
                store.put(ACCOUNT, str(new_balance)),
                store.put(REQUEST, json.dumps(result)),
            ],
        )

        if committed:
            print("Committed balance and request result together")
            return result

        # Another operation changed the state. Read it again.

    raise RuntimeError("Too much concurrent activity; try again")


first = deposit_once()
second = deposit_once()

current = int(store.get(ACCOUNT)["value"])

print("First response: ", first)
print("Retry response: ", second)
print("Stored balance: ", current)

assert first == second
assert current == 1200

print("PASS: retry did not apply the deposit twice")

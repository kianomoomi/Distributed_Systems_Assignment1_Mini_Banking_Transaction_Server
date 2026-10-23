import json

from leadership import LEADER_KEY

MAX_BALANCE = 1_000_000_000_000

INITIAL_ACCOUNTS = {
    "A1001": 100_000,
    "A1002": 50_000,
    "A1003": 200_000,
}


class BankState:
    def __init__(self, store, leadership):
        self.store = store
        self.leadership = leadership

    def initialize(self):
        for account, balance in INITIAL_ACCOUNTS.items():
            key = f"/bank/accounts/{account}"

            created = self.store.transaction(
                [
                    self.leadership.fence(),
                    self.store.missing(key),
                ],
                [self.store.put(key, str(balance))],
            )

            if not created:
                # A failed comparison can mean the account already exists
                # or that we no longer own the primary role.
                self.require_primary()

                if self.store.get(key) is None:
                    raise RuntimeError("Account initialization must be retried")

    def require_primary(self):
        valid = self.store.transaction(
            [self.leadership.fence()],
            [],
        )

        if not valid:
            raise RuntimeError("Primary ownership was lost")

    def execute(self, request):
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object")

        request_id = request.get("request_id")
        action = request.get("action")
        account = request.get("account")

        if (
            not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 128
            or any(
                character not in
                "abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789-_"
                for character in request_id
            )
        ):
            raise ValueError(
                "request_id must contain 1-128 letters, digits, - or _"
            )

        if action not in ("balance", "deposit", "withdraw"):
            raise ValueError("Unsupported action")

        if not isinstance(account, str) or not account:
            raise ValueError("Missing or invalid account")

        if account not in INITIAL_ACCOUNTS:
            # Unknown accounts are handled below without creating a key.
            account_key = None
        else:
            account_key = f"/bank/accounts/{account}"

        amount = request.get("amount")

        if action != "balance":
            if type(amount) is not int or not 0 < amount <= MAX_BALANCE:
                raise ValueError(
                    "Amount must be positive integer cents within the limit"
                )

        # Store the operation details to detect conflicting reuse of an ID.
        operation = {
            "action": action,
            "account": account,
            "amount": amount if action != "balance" else None,
        }

        request_key = f"/bank/requests/{request_id}"

        for _ in range(30):
            fence = self.leadership.fence()
            saved = self.store.get(request_key)

            if saved is not None:
                record = json.loads(saved["value"])

                if record["operation"] != operation:
                    raise ValueError(
                        "Request ID was already used for a different operation"
                    )

                # Check ownership before returning the previous result.
                if not self.store.transaction([fence], []):
                    raise RuntimeError("Primary ownership was lost")

                return record["response"]

            comparisons = [
                fence,
                self.store.missing(request_key),
            ]
            writes = []

            response = {
                "status": "error",
                "request_id": request_id,
            }

            if account_key is None:
                response["message"] = "Unknown account"

            else:
                current = self.store.get(account_key)

                if current is None:
                    raise RuntimeError("Accounts have not been initialized")

                comparisons.append(
                    self.store.unchanged(
                        account_key, current["revision"]
                    )
                )

                balance = int(current["value"])
                new_balance = balance

                if action == "deposit":
                    new_balance += amount
                elif action == "withdraw":
                    new_balance -= amount

                if new_balance < 0:
                    response["message"] = "Insufficient funds"
                elif new_balance > MAX_BALANCE:
                    response["message"] = "Balance exceeds the supported limit"
                else:
                    response = {
                        "status": "success",
                        "request_id": request_id,
                        "account": account,
                        "balance": new_balance,
                        "unit": "cents",
                    }

                    if action != "balance":
                        writes.append(
                            self.store.put(account_key, str(new_balance))
                        )

            record = {
                "operation": operation,
                "response": response,
            }

            writes.append(
                self.store.put(request_key, json.dumps(record))
            )

            if self.store.transaction(comparisons, writes):
                return response

            # A comparison failed. Verify ownership, then reread state.
            self.require_primary()

        raise RuntimeError("Account is busy; retry using the same request ID")

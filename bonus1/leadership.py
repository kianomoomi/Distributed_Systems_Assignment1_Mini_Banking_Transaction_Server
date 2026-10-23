import argparse
import time
import uuid

from etcd_store import EtcdStore

LEADER_KEY = "/bank/primary"
LEASE_SECONDS = 10
RENEW_SECONDS = 2


class Leadership:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self.token = None

    def tick(self):
        """Acquire ownership or renew existing ownership."""
        if self.token is None:
            current = self.store.get(LEADER_KEY)

            if current is not None:
                return False

            # A new token for EVERY leadership term.
            candidate = f"{self.name}:{uuid.uuid4().hex}"
            lease = self.store.grant_lease(LEASE_SECONDS)

            acquired = self.store.transaction(
                [self.store.missing(LEADER_KEY)],
                [
                    self.store.put_with_lease(
                        LEADER_KEY, candidate, lease
                    )
                ],
            )

            if acquired:
                self.token = candidate
                print(f"PRIMARY: {self.token}", flush=True)

            return acquired

        token = self.token
        lease = self.store.grant_lease(LEASE_SECONDS)

        renewed = self.store.transaction(
            [self.store.equals(LEADER_KEY, token)],
            [self.store.put_with_lease(LEADER_KEY, token, lease)],
        )

        if not renewed:
            self.token = None
            print("BACKUP: ownership no longer matches", flush=True)

        return renewed

    def fence(self):
        """Return a condition that every banking transaction must check."""
        token = self.token

        if token is None:
            raise RuntimeError("This server is not the primary")

        return self.store.equals(LEADER_KEY, token)

    def run(self):
        print(f"{self.name}: waiting for primary ownership", flush=True)

        while True:
            try:
                self.tick()
            except RuntimeError as error:
                # Fail closed when database access is uncertain.
                self.token = None
                print(f"BACKUP: {error}", flush=True)

            time.sleep(RENEW_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Banking primary election")
    parser.add_argument("--name", required=True, choices=["A", "B"])
    parser.add_argument("--endpoint", default="http://127.0.0.1:2379")
    args = parser.parse_args()

    store = EtcdStore(args.endpoint)
    leadership = Leadership(store, args.name)

    try:
        leadership.run()
    except KeyboardInterrupt:
        print("\nStopped; ownership will expire automatically", flush=True)


if __name__ == "__main__":
    main()

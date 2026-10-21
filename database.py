import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "bank.db"
MAX_BALANCE = 1_000_000_000_000  # In cents


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=30)

    # Ask SQLite to flush committed changes to disk.
    connection.execute("PRAGMA synchronous = FULL")

    return connection


def initialize_database():
    connection = connect()

    try:
        with connection:
            connection.execute(f"""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    balance_cents INTEGER NOT NULL
                        CHECK (
                            typeof(balance_cents) = 'integer'
                            AND balance_cents BETWEEN 0 AND {MAX_BALANCE}
                        )
                )
            """)

            # Existing accounts keep their balances after a restart.
            connection.executemany(
                """
                INSERT OR IGNORE INTO accounts
                    (account_id, balance_cents)
                VALUES (?, ?)
                """,
                [
                    ("A1001", 100_000),
                    ("A1002", 50_000),
                    ("A1003", 200_000),
                ],
            )
    finally:
        connection.close()


def bank_operation(action, account, amount_cents=None, fail_before_commit=False):
    if action not in ("balance", "deposit", "withdraw"):
        raise ValueError("Unsupported action")

    if not isinstance(account, str) or not account.strip():
        raise ValueError("Account must be a non-empty string")

    if action != "balance":
        # Exact type check also rejects True and False.
        if type(amount_cents) is not int or amount_cents <= 0:
            raise ValueError("Amount must be a positive integer number of cents")

        if amount_cents > MAX_BALANCE:
            raise ValueError("Amount exceeds the supported limit")

    connection = connect()

    try:
        if action != "balance":
            # Reserve the write transaction BEFORE reading the balance.
            connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            "SELECT balance_cents FROM accounts WHERE account_id = ?",
            (account,),
        ).fetchone()

        if row is None:
            raise ValueError("Unknown account")

        balance = row[0]

        if action == "balance":
            return balance

        if action == "deposit":
            new_balance = balance + amount_cents
        else:
            if amount_cents > balance:
                raise ValueError("Insufficient funds")
            new_balance = balance - amount_cents

        if new_balance > MAX_BALANCE:
            raise ValueError("Balance exceeds the supported limit")

        connection.execute(
            "UPDATE accounts SET balance_cents = ? WHERE account_id = ?",
            (new_balance, account),
        )

        # Used later to demonstrate a failure halfway through.
        if fail_before_commit:
            raise RuntimeError("Simulated failure before commit")

        connection.commit()
        return new_balance

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    initialize_database()
    print(f"Database ready: {DB_PATH}")

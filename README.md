# Mini Banking Transaction Server

Mandatory implementation for Distributed Systems Assignment 1.

## Environment

- Ubuntu 24.04 on two separate Parallels virtual machines
- Python 3.12.3
- SQLite 3.45.1
- No third-party Python packages

## Deployment

- Server VM: 10.37.129.4
- Client VM: 10.37.129.3
- TCP port: 5000

The client connects to the server VM's network IP, not localhost.

## Files

- database.py: persistent accounts and transactional banking operations
- server.py: concurrent TCP server, validation, client limit, and logging
- client.py: command-line client
- test_client.py: network error, rollback, and concurrency tests

## Start the server

On the server VM, from the project directory:

```bash
python3 server.py --max-clients 20 --demo-mode
```

The database is initialized automatically. Existing balances are preserved.

For ordinary operation without failure simulation:

```bash
python3 server.py --max-clients 20
```

## Run the client

On the client VM:

```bash
python3 client.py balance A1001 --host 10.37.129.4
python3 client.py deposit A1001 20000 --host 10.37.129.4
python3 client.py withdraw A1001 5000 --host 10.37.129.4
```

Amounts and balances are integer cents: 100 means 1.00 currency unit.

## Protocol

Each TCP connection carries one UTF-8 JSON request ending in a newline.
The server returns one JSON response ending in a newline and closes
the connection. Requests must fit within 4096 bytes.

Example request:

{"action":"withdraw","account":"A1001","amount":200}

Example success response:

{"status":"success","account":"A1001","balance":99800,
"unit":"cents","request_id":"generated-id"}

Example error response:

{"status":"error","message":"Insufficient funds",
"request_id":"generated-id"}

## Initial fictional accounts

| Account | Balance in cents |
|---------|------------------|
| A1001   | 100000           |
| A1002   | 50000            |
| A1003   | 200000           |

## Tests

Start the server with --demo-mode and at least 10 client slots, then
run on the client VM:

```bash
python3 test_client.py --host 10.37.129.4
```

Tests change balances temporarily and assume no unrelated clients are
modifying the tested accounts.

To demonstrate rollback manually:

```bash
python3 client.py deposit A1001 12345 --fail-before-commit
```

The operation returns an error and leaves the balance unchanged.

To demonstrate durability:
1. Make a deposit and record the successful response balance.
2. Find the server PID using: pgrep -af 'python3 server.py'
3. Kill that PID using: kill -9 PID
4. Restart the server without deleting database or journal files.
5. Query the account and compare its balance with the recorded value.

## Logging

bank.log contains JSON request/response entries, including request ID,
client IP, action, account, timestamp, result, latency, and delivery status.

## Scope

This version implements the mandatory single-server requirements.
Automatic failover and network-partition handling are not implemented.
The client does not automatically retry requests with uncertain outcomes.

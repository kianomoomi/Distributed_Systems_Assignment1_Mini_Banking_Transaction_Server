# Mini Banking Transaction Server

Distributed Systems Assignment 1 — mandatory implementation and both bonuses.

A simulated banking system supporting balance inquiries, deposits, and withdrawals. All accounts are fictional, and all amounts are **integer cents**.

## Features

| Part | Implementation |
|---|---|
| Mandatory | Concurrent TCP server, SQLite transactions, validation, logging, rollback, and crash durability |
| Bonus 1 — Section 5 | Primary–backup failover, replicated etcd storage, automatic client retries, and request deduplication |
| Bonus 2 — Section 6 | Real network-partition demonstration, split-brain prevention, and automatic recovery |

## Environment

- Ubuntu 24.04 ARM64 VMs in Parallels
- Python **3.12.3**
- SQLite **3.45.1**
- etcd **3.4.30**
- nftables for the partition demonstration
- No third-party Python packages

| VM | IP | Role |
|---|---|---|
| Server A | `10.211.55.4` | Banking server A and etcd node-a |
| Server B | `10.211.55.5` | Banking server B and etcd node-b |
| Client | `10.211.55.3` | Banking clients and full etcd node-c |

Clients run on a separate VM and connect to actual server IPs.

## Repository Layout

- Root Python files: mandatory implementation.
- [`bonus1/`](bonus1/): fault-tolerant banking implementation and tests.
- [`bonus2/`](bonus2/): partition rules, recovery script, probe, and instructions.
- Final report: architecture, correctness explanations, and validation results.

## Mandatory Implementation

On Server A:

```bash
python3 server.py --max-clients 20 --demo-mode
```

On the client:

```bash
python3 client.py balance A1001 --host 10.211.55.4
python3 client.py deposit A1001 20000 --host 10.211.55.4
python3 client.py withdraw A1001 5000 --host 10.211.55.4
python3 test_client.py --host 10.211.55.4
```

The server listens on **port 5000**. Demo mode enables controlled failure injection; omit it for ordinary operation.

Initial balances:

| Account | Cents |
|---|---:|
| A1001 | 100000 |
| A1002 | 50000 |
| A1003 | 200000 |

Each connection carries one newline-terminated JSON request and response:

```json
{"action":"withdraw","account":"A1001","amount":200}
```

Threads handle clients concurrently. A configurable semaphore limits active handlers. SQLite `BEGIN IMMEDIATE` protects balance changes, exceptions trigger rollback, and commits complete before success responses.

Validation covers unknown accounts, insufficient funds, invalid amounts, unsupported actions, missing fields, and malformed requests. Structured logs are written to `bank.log`.

## Bonus 1: Fault-Tolerant Cluster

Start all three etcd members using their own persistent data directories. Check health:

```bash
ETCDCTL_API=3 etcdctl \
  --endpoints=http://10.211.55.4:2379,http://10.211.55.5:2379,http://10.211.55.3:2379 \
  endpoint health
```

From the bonus source directory, start A first and wait for `primary_ready`, then start B:

```bash
# Server A
python3 bonus_server.py --name A

# Server B
python3 bonus_server.py --name B
```

On the client:

```bash
python3 bonus_client.py balance A1001
python3 bonus_workload.py
```

Bonus banking uses **port 5001**. etcd uses **2379** for its API and **2380** for replication.

### Correctness

- Three full etcd replicas require a majority of two to commit.
- A ten-second lease identifies the banking primary.
- Atomic ownership checks prevent stale-primary writes.
- Balance updates and completed request records commit together.
- Retries preserve the request ID and return saved results.
- Reusing an ID for different operation details is rejected.

The banking primary and etcd replication leader are separate roles.

### Demonstrations

1. Kill A’s banking process during the workload; B takes over automatically.
2. Start A with `--reply-delay 20`, then kill it after a matching `reply_delayed` event. The client retries through B without applying the deposit twice.

The workload performs 30 deposits of 100 cents and 30 withdrawals of 40 cents, checking an expected net increase of **1800 cents**.

## Bonus 2: Network Partition

While A is primary and the workload is active, apply on **Server A only**:

```bash
sudo nft -c -f partition.nft
sudo nft -f partition.nft
sudo nft list table inet bank_partition
```

The rules block A–B communication and A’s replication traffic with node-c. Client banking connections remain available.

During the partition:

- Both banking processes and all etcd processes remain running.
- Isolated A cannot commit through a majority.
- B and node-c retain a majority and continue service.
- A refuses fresh banking operations.

On the client:

```bash
python3 probe_isolated.py
```

Restore connectivity on A:

```bash
sudo nft delete table inet bank_partition
```

No service restart is required. Verify cluster health and the workload’s final balance after recovery.

## Verified Results

- Mandatory concurrency, overdraft prevention, rollback, client-limit, and restart checks passed.
- The continuous workload completed after primary failure.
- A committed 700-cent deposit with a lost reply was recovered through B; duplicate retries did not change the balance again.
- During partition testing, A returned a retryable refusal while B served requests.
- After reconnection, all three endpoints were healthy and consistent reads agreed with the expected final balance.

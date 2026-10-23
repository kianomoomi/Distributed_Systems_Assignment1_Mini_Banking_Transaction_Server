#!/usr/bin/env bash
set -euo pipefail

# Run on Server A only.
if sudo nft list table inet bank_partition >/dev/null 2>&1; then
    sudo nft delete table inet bank_partition
    echo "Partition removed; network connectivity restored."
else
    echo "No bank_partition table exists."
fi

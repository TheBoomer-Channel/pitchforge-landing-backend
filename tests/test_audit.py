"""Smoke tests for audit hash chain (TASK-014).

The audit DB operations require MongoDB. These tests cover the pure
hash-chaining logic which is the core correctness invariant.
"""

from __future__ import annotations

import json

from app.models.audit import GENESIS_HASH, compute_chain_hash


def test_genesis_hash_is_64_zeros():
    assert GENESIS_HASH == "0" * 64


def test_hash_is_deterministic():
    row = {"seq": 1, "action": "auth.login.success", "user_id": "u1"}
    h1 = compute_chain_hash(GENESIS_HASH, row)
    h2 = compute_chain_hash(GENESIS_HASH, row)
    assert h1 == h2
    assert len(h1) == 64


def test_different_prev_hash_yields_different_this_hash():
    row = {"seq": 1, "action": "auth.login.success", "user_id": "u1"}
    h1 = compute_chain_hash(GENESIS_HASH, row)
    h2 = compute_chain_hash("a" * 64, row)
    assert h1 != h2


def test_different_row_yields_different_hash():
    h1 = compute_chain_hash(GENESIS_HASH, {"seq": 1, "action": "auth.login.success", "user_id": "u1"})
    h2 = compute_chain_hash(GENESIS_HASH, {"seq": 1, "action": "auth.login.success", "user_id": "u2"})
    assert h1 != h2


def test_canonical_json_key_order_independence():
    """Two dicts with the same keys in different orders must hash the same."""
    h1 = compute_chain_hash(GENESIS_HASH, {"a": 1, "b": 2, "c": 3})
    h2 = compute_chain_hash(GENESIS_HASH, {"c": 3, "a": 1, "b": 2})
    assert h1 == h2


def test_tamper_detection():
    """If any field in a row changes after the fact, the hash no longer matches."""
    row = {"seq": 1, "action": "auth.login.success", "user_id": "u1", "ip": "1.2.3.4"}
    h_original = compute_chain_hash(GENESIS_HASH, row)
    # Attacker modifies the IP
    row_tampered = {**row, "ip": "9.9.9.9"}
    h_tampered = compute_chain_hash(GENESIS_HASH, row_tampered)
    assert h_original != h_tampered


def test_chain_breaks_when_row_inserted_in_middle():
    """Simulating an attacker inserting a row in the middle of the chain."""
    # Original chain: e1 (seq=1) → e2 (seq=2) → e3 (seq=3)
    e1 = compute_chain_hash(GENESIS_HASH, {"seq": 1, "action": "a"})
    e2 = compute_chain_hash(e1, {"seq": 2, "action": "b"})
    e3 = compute_chain_hash(e2, {"seq": 3, "action": "c"})

    # Attacker inserts a new event between 2 and 3
    e2_5 = compute_chain_hash(e2, {"seq": 99, "action": "EVIL"})

    # Now e3.prev_hash must equal e2.this_hash for the chain to verify
    # but e2_5 ≠ e2, so the chain breaks at e3
    assert e2_5 != e2
    # The verifier would notice e3.prev_hash ≠ e2_5.this_hash (assuming the
    # attacker didn't also rewrite e3.prev_hash)

"""End-to-end tests for arsenal/."""
from __future__ import annotations

import time

import pytest

from arsenal import (
    generate_keypair, load_keypair, mint, verify, inspect,
    set_session_tokens, requires_token,
    sign_blob, verify_blob,
    MissingToken, ExhaustedToken, ExpiredToken, TokenError, ConditionNotMet,
)
from arsenal.enforcer import clear_session_tokens, InMemoryUsageStore


# ── keys ─────────────────────────────────────────────────────────────
def test_keygen_and_load(tmp_path):
    k1 = generate_keypair(directory=tmp_path)
    k2 = load_keypair(directory=tmp_path)
    assert k1.kid == k2.kid
    assert k1.public_bytes == k2.public_bytes
    assert k1.has_private and k2.has_private
    assert len(k1.kid) == 8


def test_keygen_no_overwrite(tmp_path):
    generate_keypair(directory=tmp_path)
    with pytest.raises(FileExistsError):
        generate_keypair(directory=tmp_path)
    # overwrite=True works
    generate_keypair(directory=tmp_path, overwrite=True)


# ── tokens: mint / verify / inspect ─────────────────────────────────
def test_mint_and_verify_roundtrip(tmp_path):
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="refunds.issue", agent="cs-v2", session="sess-1",
               key=key, ttl_seconds=60,
               limits={"calls": 5, "cumulative_gbp": 200},
               conditions=[{"op": "hold_above_gbp", "value": 50}])
    assert raw.count(".") == 2
    tok = verify(raw, trusted_keys=[key])
    assert tok.tool == "refunds.issue"
    assert tok.agent == "cs-v2"
    assert tok.session == "sess-1"
    assert tok.limits == {"calls": 5, "cumulative_gbp": 200}
    assert not tok.is_expired


def test_inspect_does_not_verify(tmp_path):
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="x.read", agent="a", session="s", key=key)
    # tamper the signature
    h, p, _ = raw.split(".")
    bad = f"{h}.{p}.deadbeef"
    # inspect succeeds (it doesn't check sig)
    inspect(bad)
    # verify rejects
    with pytest.raises(TokenError):
        verify(bad, trusted_keys=[key])


def test_verify_rejects_expired(tmp_path):
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="x.read", agent="a", session="s", key=key, ttl_seconds=1)
    time.sleep(1.2)
    with pytest.raises(ExpiredToken):
        verify(raw, trusted_keys=[key])


def test_verify_rejects_unknown_issuer(tmp_path):
    k1 = generate_keypair(directory=tmp_path / "k1")
    k2 = generate_keypair(directory=tmp_path / "k2")
    raw = mint(tool="x.read", agent="a", session="s", key=k1)
    with pytest.raises(TokenError):
        verify(raw, trusted_keys=[k2])


def test_mint_rejects_oversize_ttl(tmp_path):
    key = generate_keypair(directory=tmp_path)
    with pytest.raises(ValueError):
        mint(tool="x.read", agent="a", session="s", key=key,
             ttl_seconds=24 * 60 * 60 + 1)


def test_mint_rejects_bad_tool_name(tmp_path):
    key = generate_keypair(directory=tmp_path)
    with pytest.raises(ValueError):
        mint(tool="bad name with spaces", agent="a", session="s", key=key)


# ── sign/verify generic blob ─────────────────────────────────────────
def test_sign_verify_blob(tmp_path):
    key = generate_keypair(directory=tmp_path)
    blob = b'{"composite":0.91,"rating":"AAA"}'
    sig = sign_blob(blob, key=key)
    assert sig.startswith(key.kid + ".")
    verified_key = verify_blob(blob, sig, trusted_keys=[key])
    assert verified_key.kid == key.kid


def test_sign_verify_blob_tampered(tmp_path):
    key = generate_keypair(directory=tmp_path)
    blob = b'{"composite":0.91}'
    sig = sign_blob(blob, key=key)
    with pytest.raises(TokenError):
        verify_blob(b'{"composite":0.10}', sig, trusted_keys=[key])


# ── enforcer: requires_token decorator ───────────────────────────────
def test_enforcer_blocks_without_token(tmp_path):
    clear_session_tokens()

    @requires_token("refunds.issue")
    def issue(amount_gbp: float):
        return f"refunded £{amount_gbp}"

    with pytest.raises(MissingToken):
        issue(amount_gbp=10)


def test_enforcer_allows_with_valid_token(tmp_path):
    clear_session_tokens()
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="refunds.issue", agent="a", session="s", key=key,
               limits={"calls": 3, "cumulative_gbp": 100})
    tok = verify(raw, trusted_keys=[key])
    set_session_tokens([tok])

    store = InMemoryUsageStore()

    @requires_token("refunds.issue", store=store)
    def issue(amount_gbp: float):
        return f"ok £{amount_gbp}"

    assert issue(amount_gbp=20) == "ok £20"
    assert issue(amount_gbp=30) == "ok £30"
    u = store.get(tok)
    assert u.calls == 2 and u.cumulative_gbp == 50


def test_enforcer_blocks_when_calls_exhausted(tmp_path):
    clear_session_tokens()
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="x.do", agent="a", session="s", key=key,
               limits={"calls": 2})
    set_session_tokens([verify(raw, trusted_keys=[key])])

    store = InMemoryUsageStore()

    @requires_token("x.do", store=store)
    def do():
        return "ok"

    do(); do()
    with pytest.raises(ExhaustedToken):
        do()


def test_enforcer_blocks_when_gbp_exhausted(tmp_path):
    clear_session_tokens()
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="refunds.issue", agent="a", session="s", key=key,
               limits={"cumulative_gbp": 100})
    set_session_tokens([verify(raw, trusted_keys=[key])])

    store = InMemoryUsageStore()

    @requires_token("refunds.issue", store=store)
    def issue(amount_gbp):
        return "ok"

    issue(amount_gbp=60)
    issue(amount_gbp=30)
    with pytest.raises(ExhaustedToken):
        issue(amount_gbp=20)  # would push total to 110 > 100


def test_enforcer_max_arg_gbp_condition(tmp_path):
    clear_session_tokens()
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="refunds.issue", agent="a", session="s", key=key,
               conditions=[{"op": "max_arg_gbp", "value": 100}])
    set_session_tokens([verify(raw, trusted_keys=[key])])

    @requires_token("refunds.issue")
    def issue(amount_gbp):
        return "ok"

    assert issue(amount_gbp=80) == "ok"
    with pytest.raises(ConditionNotMet):
        issue(amount_gbp=200)


def test_enforcer_hold_above_gbp_marks_result(tmp_path):
    clear_session_tokens()
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="refunds.issue", agent="a", session="s", key=key,
               conditions=[{"op": "hold_above_gbp", "value": 50}])
    set_session_tokens([verify(raw, trusted_keys=[key])])

    @requires_token("refunds.issue")
    def issue(amount_gbp):
        return f"sent £{amount_gbp}"

    assert issue(amount_gbp=20) == "sent £20"
    held = issue(amount_gbp=200)
    assert isinstance(held, dict) and held.get("__nail_hold__") is True


def test_enforcer_blocks_expired_token(tmp_path):
    clear_session_tokens()
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="x.read", agent="a", session="s", key=key, ttl_seconds=1)
    tok = inspect(raw)  # don't verify (would fail if we waited first)
    set_session_tokens([tok])

    @requires_token("x.read")
    def go():
        return "ok"

    assert go() == "ok"
    time.sleep(1.2)
    with pytest.raises(ExpiredToken):
        go()


def test_enforcer_unknown_condition_fails_closed(tmp_path):
    clear_session_tokens()
    key = generate_keypair(directory=tmp_path)
    raw = mint(tool="x.read", agent="a", session="s", key=key,
               conditions=[{"op": "future_op_not_yet_implemented", "value": 1}])
    set_session_tokens([verify(raw, trusted_keys=[key])])

    @requires_token("x.read")
    def go():
        return "ok"

    with pytest.raises(ConditionNotMet):
        go()

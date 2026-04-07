"""Tests for helper utility functions."""

from dydx3.helpers.request_helpers import (
    epoch_seconds_to_iso,
    generate_now_iso,
    generate_query_path,
    iso_to_epoch_seconds,
    json_stringify,
    random_client_id,
    remove_nones,
)
from dydx3.helpers.db import get_account_id, get_user_id


class TestQueryPath:

    def test_empty_params(self):
        assert generate_query_path('/v3/markets', {}) == '/v3/markets'

    def test_single_param(self):
        result = generate_query_path('/v3/markets', {'market': 'BTC-USD'})
        assert result == '/v3/markets?market=BTC-USD'

    def test_multiple_params(self):
        result = generate_query_path(
            '/v3/orders',
            {'market': 'ETH-USD', 'status': 'OPEN'},
        )
        assert 'market=ETH-USD' in result
        assert 'status=OPEN' in result

    def test_none_values_filtered(self):
        result = generate_query_path(
            '/v3/markets',
            {'market': 'BTC-USD', 'status': None},
        )
        assert result == '/v3/markets?market=BTC-USD'

    def test_all_none_values(self):
        result = generate_query_path('/v3/markets', {'a': None, 'b': None})
        assert result == '/v3/markets'


class TestJsonStringify:

    def test_compact_json(self):
        assert json_stringify({'a': 1, 'b': 2}) == '{"a":1,"b":2}'

    def test_empty_dict(self):
        assert json_stringify({}) == '{}'


class TestRandomClientId:

    def test_returns_string(self):
        assert isinstance(random_client_id(), str)

    def test_unique(self):
        ids = {random_client_id() for _ in range(100)}
        assert len(ids) > 50  # Should be mostly unique


class TestIsoConversions:

    def test_roundtrip(self):
        iso = '2021-01-01T00:00:00.000Z'
        epoch = iso_to_epoch_seconds(iso)
        result = epoch_seconds_to_iso(epoch)
        assert result == iso

    def test_generate_now_iso_format(self):
        now = generate_now_iso()
        assert now.endswith('Z')
        assert 'T' in now


class TestRemoveNones:

    def test_remove_nones(self):
        assert remove_nones({'a': 1, 'b': None, 'c': 3}) == {'a': 1, 'c': 3}

    def test_empty_dict(self):
        assert remove_nones({}) == {}

    def test_all_nones(self):
        assert remove_nones({'a': None}) == {}

    def test_no_nones(self):
        assert remove_nones({'a': 1}) == {'a': 1}


class TestDbHelpers:

    def test_get_user_id_deterministic(self):
        addr = '0x1234567890abcdef1234567890abcdef12345678'
        assert get_user_id(addr) == get_user_id(addr)

    def test_get_account_id_deterministic(self):
        addr = '0x1234567890abcdef1234567890abcdef12345678'
        assert get_account_id(addr) == get_account_id(addr)

    def test_get_account_id_case_insensitive(self):
        addr_lower = '0x1234567890abcdef1234567890abcdef12345678'
        addr_upper = '0x1234567890ABCDEF1234567890ABCDEF12345678'
        assert get_account_id(addr_lower) == get_account_id(addr_upper)

    def test_different_account_numbers(self):
        addr = '0x1234567890abcdef1234567890abcdef12345678'
        assert get_account_id(addr, 0) != get_account_id(addr, 1)

from __future__ import annotations

from valkey_scale_lab.workload import SLOT_COUNT, generate_benchmark_keys, slot_for_key


def test_cluster_hash_tag_slot_matches_same_tag() -> None:
    assert slot_for_key("{user1000}.following") == slot_for_key("{user1000}.followers")
    assert slot_for_key("foo:bar") != slot_for_key("{foo}:bar")


def test_full_slot_generator_covers_every_slot() -> None:
    keys, coverage = generate_benchmark_keys(profile="uniform", hash_slot_distribution="full_slot", prefix="unit")

    assert len(keys) == SLOT_COUNT
    assert coverage["slot_count_observed"] == SLOT_COUNT
    assert coverage["full_slot_requested"] is True
    assert coverage["full_slot_covered"] is True
    assert coverage["fixed_hash_tag_only"] is False


def test_single_tag_is_not_benchmark_default() -> None:
    _, coverage = generate_benchmark_keys(profile="smoke", hash_slot_distribution="single_tag", prefix="unit")

    assert coverage["slot_count_observed"] == 1
    assert coverage["fixed_hash_tag_only"] is True

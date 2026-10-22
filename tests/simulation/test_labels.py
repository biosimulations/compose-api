"""Labels, tags and descriptions on simulations (compose_api/simulation/labels.py)."""

import pytest

from compose_api.simulation.labels import LabelError, clean_description, clean_tags, labels, parse_label_filters


def test_tags_are_trimmed_and_deduplicated_in_order() -> None:
    assert clean_tags([" b ", "a", "b", "BIOMD0000000012", "run 2/3"]) == ["b", "a", "BIOMD0000000012", "run 2/3"]
    assert clean_tags(None) == []


@pytest.mark.parametrize("tag", ["", " ", "-x", "x" * 65, "new\nline", "semi;colon"])
def test_a_malformed_tag_is_refused(tag: str) -> None:
    with pytest.raises(LabelError):
        clean_tags([tag])


def test_at_most_twenty_tags() -> None:
    with pytest.raises(LabelError):
        clean_tags([f"t{i}" for i in range(21)])


def test_descriptions_are_trimmed_and_bounded() -> None:
    assert clean_description("  why  ") == "why"
    assert clean_description("   ") is None
    with pytest.raises(LabelError):
        clean_description("x" * 2001)


def test_service_labels_use_reserved_keys_and_drop_none() -> None:
    assert labels(source="upload", environment="registry_env", solver=None) == {
        "source": "upload",
        "environment": "registry_env",
    }
    with pytest.raises(ValueError):
        labels(colour="red")


def test_label_filters_are_key_value_with_a_known_key() -> None:
    assert parse_label_filters(["model:BIOMD0000000012", "project:a:b"]) == {
        "model": "BIOMD0000000012",
        "project": "a:b",
    }
    for bad in ["model", "model:", "colour:red", ":x"]:
        with pytest.raises(LabelError):
            parse_label_filters([bad])

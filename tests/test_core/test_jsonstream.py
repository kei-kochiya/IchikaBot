import json

import pytest

from utils.core.jsonstream import count_json_array, iter_json_array

SAMPLE = [
    {"id": i, "text": 'quote " comma , bracket ] 日本語', "n": [1, 2.5, None, True]}
    for i in range(40)
]


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 64, 1 << 20])
@pytest.mark.parametrize(
    "dump_kwargs",
    [
        {},
        {"indent": 2},
        {"separators": (",", ":")},
        {"ensure_ascii": False, "indent": 1},
    ],
)
def test_matches_json_load_for_any_layout_and_chunk_boundary(tmp_path, chunk_size, dump_kwargs):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(SAMPLE, **dump_kwargs), encoding="utf-8")

    assert list(iter_json_array(path, chunk_size=chunk_size)) == SAMPLE


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 64])
def test_bare_scalars_are_not_truncated_at_buffer_edges(tmp_path, chunk_size):
    path = tmp_path / "scalars.json"
    values = [1, 22, 333, 4.5e10, True, None, "str", [1, [2]]]
    path.write_text(json.dumps(values), encoding="utf-8")

    assert list(iter_json_array(path, chunk_size=chunk_size)) == values


@pytest.mark.parametrize("text", [" [ ] ", "[]", "\n[\n]\n"])
def test_empty_array(tmp_path, text):
    path = tmp_path / "empty.json"
    path.write_text(text, encoding="utf-8")

    assert list(iter_json_array(path)) == []
    assert count_json_array(path) == 0


@pytest.mark.parametrize("text", ['{"a": 1}', "[1, 2", "[1 2]", "[{]", "", "[1,]", "nope"])
def test_malformed_input_raises_value_error(tmp_path, text):
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError):
        list(iter_json_array(path))


def test_elements_are_yielded_lazily(tmp_path):
    path = tmp_path / "lazy.json"
    path.write_text(json.dumps([{"id": 1}, {"id": 2}]) + " trailing garbage?", encoding="utf-8")

    it = iter_json_array(path)
    assert next(it) == {"id": 1}  # the first element is available before the rest is parsed


def test_count_json_array(tmp_path):
    path = tmp_path / "count.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")

    assert count_json_array(path) == len(SAMPLE)

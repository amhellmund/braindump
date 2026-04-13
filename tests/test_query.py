# Copyright 2026 Andi Hellmund
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for query pipeline helpers."""

from braindump.query import _extract_citations, _parse_index_summaries

########################################################################################################################
# _parse_index_summaries                                                                                               #
########################################################################################################################

_UUID_A = "11111111-1111-1111-1111-111111111111"
_UUID_B = "22222222-2222-2222-2222-222222222222"

_INDEX_TWO_SPIKES = f"""\
# Braindump Index

## {_UUID_A}
**Title:** Alpha spike
**Tags:** foo, bar
**Created:** 2025-01-01T00:00:00+00:00
**Summary:** This spike covers the alpha technique in depth.
**Related:** {_UUID_B}

## {_UUID_B}
**Title:** Beta spike
**Tags:** baz
**Created:** 2025-01-02T00:00:00+00:00
**Summary:** Beta explores complementary ideas to alpha.
"""


def test_parse_index_summaries_extracts_both():
    result = _parse_index_summaries(_INDEX_TWO_SPIKES)
    assert result[_UUID_A] == "This spike covers the alpha technique in depth."
    assert result[_UUID_B] == "Beta explores complementary ideas to alpha."


def test_parse_index_summaries_empty_index():
    assert _parse_index_summaries("# Braindump Index\n\nNo spikes yet.\n") == {}


def test_parse_index_summaries_section_without_summary():
    content = f"## {_UUID_A}\n**Title:** Broken spike\n**Tags:** x\n"
    assert _parse_index_summaries(content) == {}


def test_parse_index_summaries_ignores_non_uuid_headings():
    content = f"## Not a UUID\nsome text\n\n## {_UUID_A}\n**Summary:** Real summary.\n"
    result = _parse_index_summaries(content)
    assert list(result) == [_UUID_A]
    assert result[_UUID_A] == "Real summary."


########################################################################################################################
# _extract_citations                                                                                                   #
########################################################################################################################

_SPIKE_REF = [
    {"index": 1, "id": _UUID_A, "title": "Alpha spike", "tags": ["foo"]},
    {"index": 2, "id": _UUID_B, "title": "Beta spike", "tags": ["baz"]},
]

_SUMMARIES = {
    _UUID_A: "This spike covers the alpha technique in depth.",
    _UUID_B: "Beta explores complementary ideas to alpha.",
}


def test_extract_citations_uses_summary_snippet():
    answer = "Alpha is great [1] and beta helps [2]."
    sources = _extract_citations(answer, _SPIKE_REF, _SUMMARIES)
    assert len(sources) == 2
    assert sources[0].snippet == "This spike covers the alpha technique in depth."
    assert sources[1].snippet == "Beta explores complementary ideas to alpha."


def test_extract_citations_falls_back_to_title_when_no_summary():
    answer = "Only alpha here [1]."
    sources = _extract_citations(answer, _SPIKE_REF, {})
    assert sources[0].snippet == "Alpha spike"


def test_extract_citations_deduplicates():
    answer = "See [1] and again [1]."
    sources = _extract_citations(answer, _SPIKE_REF, _SUMMARIES)
    assert len(sources) == 1
    assert sources[0].index == 1


def test_extract_citations_skips_out_of_range_index():
    answer = "No such spike [99]."
    assert _extract_citations(answer, _SPIKE_REF, _SUMMARIES) == []


def test_extract_citations_preserves_order():
    answer = "First [2] then [1]."
    sources = _extract_citations(answer, _SPIKE_REF, _SUMMARIES)
    assert [s.index for s in sources] == [2, 1]


def test_extract_citations_snippet_truncated_to_limit():
    long_summary = "x" * 300
    summaries = {_UUID_A: long_summary}
    answer = "See [1]."
    sources = _extract_citations(answer, _SPIKE_REF, summaries)
    assert len(sources[0].snippet) == 250

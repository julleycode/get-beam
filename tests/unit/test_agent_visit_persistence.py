"""Unit tests for apps.api.services.agent_visit_persistence._append_capped_path.

Pure function — no DB, no deps. Covers empty/None/duplicate/cap-boundary cases.
"""

import pytest

from apps.api.services.agent_visit_persistence import _append_capped_path


class TestAppendCappedPath:
    @pytest.mark.unit
    def test_appends_to_empty_list(self):
        assert _append_capped_path([], "/pricing") == ["/pricing"]

    @pytest.mark.unit
    def test_none_path_is_noop(self):
        paths = ["/a", "/b"]
        result = _append_capped_path(paths, None)
        assert result == ["/a", "/b"]

    @pytest.mark.unit
    def test_empty_string_path_is_noop(self):
        paths = ["/a", "/b"]
        result = _append_capped_path(paths, "")
        assert result == ["/a", "/b"]

    @pytest.mark.unit
    def test_appends_new_distinct_path(self):
        assert _append_capped_path(["/a"], "/b") == ["/a", "/b"]

    @pytest.mark.unit
    def test_duplicate_path_moves_to_end(self):
        # Re-seeing "/a" moves it to the most-recent (end) position, no growth.
        result = _append_capped_path(["/a", "/b", "/c"], "/a")
        assert result == ["/b", "/c", "/a"]

    @pytest.mark.unit
    def test_ordering_is_oldest_first_most_recent_last(self):
        result = _append_capped_path([], "/1")
        result = _append_capped_path(result, "/2")
        result = _append_capped_path(result, "/3")
        assert result == ["/1", "/2", "/3"]

    @pytest.mark.unit
    def test_exactly_at_cap_then_new_drops_oldest(self):
        paths = [f"/p{i}" for i in range(50)]  # exactly 50
        result = _append_capped_path(paths, "/new", cap=50)
        assert len(result) == 50
        assert "/p0" not in result  # oldest dropped
        assert result[-1] == "/new"
        assert result[0] == "/p1"

    @pytest.mark.unit
    def test_over_cap_input_defensively_trimmed(self):
        paths = [f"/p{i}" for i in range(60)]  # already over cap
        result = _append_capped_path(paths, "/new", cap=50)
        assert len(result) == 50
        assert result[-1] == "/new"

    @pytest.mark.unit
    def test_duplicate_at_cap_stays_at_cap(self):
        paths = [f"/p{i}" for i in range(50)]
        result = _append_capped_path(paths, "/p0", cap=50)  # re-see oldest
        assert len(result) == 50
        assert result[-1] == "/p0"  # moved to end
        assert result[0] == "/p1"

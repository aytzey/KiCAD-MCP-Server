from itertools import pairwise

import pytest

from commands.orthogonal_router import (
    compress_path,
    inflate_rect,
    manhattan_path_length,
    normalize_rect,
    pick_escape_point,
    plan_orthogonal_path,
    segment_direction,
    segment_intersects_rect,
    segments_conflict,
)


@pytest.mark.unit
class TestOrthogonalRouterHelpers:
    def test_normalize_and_inflate_rect(self):
        rect = normalize_rect((10, 5, 2, -1))
        assert rect == (2, -1, 10, 5)
        assert inflate_rect(rect, 0.5) == (1.5, -1.5, 10.5, 5.5)

    def test_segment_intersects_rect_allows_boundary_touch(self):
        rect = (4, -1, 6, 1)
        assert segment_intersects_rect((0, -1), (10, -1), rect, strict=True) is False
        assert segment_intersects_rect((0, 0), (10, 0), rect, strict=True) is True

    def test_segments_conflict_ignores_shared_endpoint(self):
        assert segments_conflict((0, 0), (10, 0), (10, 0), (10, 10)) is False
        assert segments_conflict((0, 0), (10, 0), (5, -5), (5, 5)) is True

    def test_compress_path_removes_duplicate_and_collinear_points(self):
        path = compress_path([(0, 0), (0, 0), (0, 5), (0, 10), (4, 10)])
        assert path == [(0, 0), (0, 10), (4, 10)]

    def test_pick_escape_point_prefers_side_facing_target(self):
        rect = (4, 4, 6, 6)
        escape = pick_escape_point((5, 5), rect, 1.0, (20, 5))
        assert escape == (7.0, 5)


@pytest.mark.unit
class TestOrthogonalRouterPlanning:
    def test_plan_orthogonal_path_without_obstacles(self):
        path = plan_orthogonal_path((0, 0), (10, 10), [])
        assert path is not None
        assert path[0] == (0, 0)
        assert path[-1] == (10, 10)
        assert manhattan_path_length(path) == pytest.approx(20.0)
        for start, end in pairwise(path):
            assert segment_direction(start, end) in {"H", "V"}

    def test_plan_orthogonal_path_routes_around_obstacle(self):
        obstacle = inflate_rect((4, -1, 6, 1), 0.0)
        path = plan_orthogonal_path((0, 0), (10, 0), [obstacle])
        assert path is not None
        assert path[0] == (0, 0)
        assert path[-1] == (10, 0)
        assert manhattan_path_length(path) > 10.0
        for start, end in pairwise(path):
            assert segment_intersects_rect(start, end, obstacle, strict=True) is False

    def test_plan_orthogonal_path_can_use_clearance_boundary_corridor(self):
        obstacles = [
            (1, -2, 9, -0.5),
            (1, 0.5, 9, 2),
            (4, -0.5, 6, 0.5),
        ]
        path = plan_orthogonal_path((0, 0), (10, 0), obstacles)
        assert path is not None
        assert path[1][1] == pytest.approx(-0.5)

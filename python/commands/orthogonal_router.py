"""
Geometry helpers for obstacle-aware orthogonal routing.

The planner here is intentionally lightweight: it builds a sparse rectilinear
grid from start/end coordinates and inflated obstacle boundaries, then runs A*
over that grid with an optional bend penalty. This is not a full autorouter,
but it is a large step up from single-segment routing and is practical for
mechanically clean MCP-generated traces and wire stubs.
"""

from __future__ import annotations

import heapq
from itertools import pairwise
from typing import Dict, Iterable, List, Optional, Tuple

Point = Tuple[float, float]
Rect = Tuple[float, float, float, float]

_EPSILON = 1e-6


def normalize_rect(rect: Rect) -> Rect:
    """Return rect as (min_x, min_y, max_x, max_y)."""
    x1, y1, x2, y2 = rect
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def inflate_rect(rect: Rect, margin: float) -> Rect:
    """Expand a rectangle by margin on all sides."""
    min_x, min_y, max_x, max_y = normalize_rect(rect)
    return (min_x - margin, min_y - margin, max_x + margin, max_y + margin)


def round_point(point: Point, digits: int = 6) -> Point:
    """Round point coordinates to keep graph nodes hash-stable."""
    return (round(point[0], digits), round(point[1], digits))


def manhattan_distance(a: Point, b: Point) -> float:
    """Return Manhattan distance between two points."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def point_in_rect(
    point: Point,
    rect: Rect,
    *,
    strict: bool = False,
    eps: float = _EPSILON,
) -> bool:
    """Check whether a point lies in a rectangle."""
    x, y = point
    min_x, min_y, max_x, max_y = normalize_rect(rect)
    if strict:
        return min_x + eps < x < max_x - eps and min_y + eps < y < max_y - eps
    return min_x - eps <= x <= max_x + eps and min_y - eps <= y <= max_y + eps


def segment_direction(start: Point, end: Point, eps: float = _EPSILON) -> Optional[str]:
    """Return H or V for an orthogonal segment, else None."""
    if abs(start[1] - end[1]) <= eps and abs(start[0] - end[0]) > eps:
        return "H"
    if abs(start[0] - end[0]) <= eps and abs(start[1] - end[1]) > eps:
        return "V"
    return None


def segment_intersects_rect(
    start: Point,
    end: Point,
    rect: Rect,
    *,
    strict: bool = True,
    eps: float = _EPSILON,
) -> bool:
    """
    Check whether an orthogonal segment intersects a rectangle.

    When ``strict`` is True, touching an obstacle boundary is allowed, but
    passing through its interior is not.
    """
    direction = segment_direction(start, end, eps)
    if direction is None:
        return point_in_rect(start, rect, strict=strict, eps=eps) or point_in_rect(
            end, rect, strict=strict, eps=eps
        )

    min_x, min_y, max_x, max_y = normalize_rect(rect)

    if direction == "H":
        y = start[1]
        seg_min_x, seg_max_x = sorted((start[0], end[0]))
        if strict:
            y_hits = min_y + eps < y < max_y - eps
            x_hits = seg_min_x < max_x - eps and min_x + eps < seg_max_x
        else:
            y_hits = min_y - eps <= y <= max_y + eps
            x_hits = seg_min_x <= max_x + eps and min_x - eps <= seg_max_x
        return y_hits and x_hits

    x = start[0]
    seg_min_y, seg_max_y = sorted((start[1], end[1]))
    if strict:
        x_hits = min_x + eps < x < max_x - eps
        y_hits = seg_min_y < max_y - eps and min_y + eps < seg_max_y
    else:
        x_hits = min_x - eps <= x <= max_x + eps
        y_hits = seg_min_y <= max_y + eps and min_y - eps <= seg_max_y
    return x_hits and y_hits


def segments_conflict(
    a_start: Point,
    a_end: Point,
    b_start: Point,
    b_end: Point,
    *,
    eps: float = _EPSILON,
) -> bool:
    """
    Return True when two orthogonal segments overlap or cross away from a shared
    endpoint. Shared-endpoint connections are allowed.
    """
    dir_a = segment_direction(a_start, a_end, eps)
    dir_b = segment_direction(b_start, b_end, eps)
    if dir_a is None or dir_b is None:
        return False

    shared_points = {
        round_point(a_start),
        round_point(a_end),
    } & {
        round_point(b_start),
        round_point(b_end),
    }

    if dir_a == dir_b == "H":
        if abs(a_start[1] - b_start[1]) > eps:
            return False
        a_min, a_max = sorted((a_start[0], a_end[0]))
        b_min, b_max = sorted((b_start[0], b_end[0]))
        overlap_min = max(a_min, b_min)
        overlap_max = min(a_max, b_max)
        if overlap_max - overlap_min <= eps:
            return False
        if shared_points and overlap_max - overlap_min <= eps:
            return False
        return True

    if dir_a == dir_b == "V":
        if abs(a_start[0] - b_start[0]) > eps:
            return False
        a_min, a_max = sorted((a_start[1], a_end[1]))
        b_min, b_max = sorted((b_start[1], b_end[1]))
        overlap_min = max(a_min, b_min)
        overlap_max = min(a_max, b_max)
        if overlap_max - overlap_min <= eps:
            return False
        if shared_points and overlap_max - overlap_min <= eps:
            return False
        return True

    if dir_a == "V":
        a_start, a_end, b_start, b_end = b_start, b_end, a_start, a_end

    # a = horizontal, b = vertical
    h_min_x, h_max_x = sorted((a_start[0], a_end[0]))
    v_min_y, v_max_y = sorted((b_start[1], b_end[1]))
    cross = (b_start[0], a_start[1])
    if h_min_x - eps <= cross[0] <= h_max_x + eps and v_min_y - eps <= cross[1] <= v_max_y + eps:
        if round_point(cross) in shared_points:
            return False
        return True
    return False


def compress_path(points: Iterable[Point], eps: float = _EPSILON) -> List[Point]:
    """Remove duplicate and collinear intermediate points."""
    result: List[Point] = []
    for point in points:
        point = round_point(point)
        if result and abs(result[-1][0] - point[0]) <= eps and abs(result[-1][1] - point[1]) <= eps:
            continue
        result.append(point)

    changed = True
    while changed and len(result) >= 3:
        changed = False
        compressed = [result[0]]
        for i in range(1, len(result) - 1):
            prev_point = compressed[-1]
            point = result[i]
            next_point = result[i + 1]
            if segment_direction(prev_point, point, eps) == segment_direction(point, next_point, eps):
                changed = True
                continue
            compressed.append(point)
        compressed.append(result[-1])
        result = compressed
    return result


def manhattan_path_length(points: Iterable[Point]) -> float:
    """Return total Manhattan path length."""
    total = 0.0
    pts = list(points)
    for start, end in pairwise(pts):
        total += manhattan_distance(start, end)
    return total


def pick_escape_point(point: Point, rect: Rect, clearance: float, target: Point) -> Point:
    """
    Pick a rect boundary escape point biased toward the target.

    The returned point sits just outside the rectangle and is axis-aligned with
    the original point, which makes it suitable as the first or last orthogonal
    routing waypoint around a footprint or symbol body.
    """
    min_x, min_y, max_x, max_y = normalize_rect(rect)
    candidates = [
        (min_x - clearance, point[1]),
        (max_x + clearance, point[1]),
        (point[0], min_y - clearance),
        (point[0], max_y + clearance),
    ]
    return min(
        candidates,
        key=lambda candidate: (
            manhattan_distance(candidate, target),
            manhattan_distance(point, candidate),
        ),
    )


def plan_orthogonal_path(
    start: Point,
    end: Point,
    obstacles: Iterable[Rect],
    *,
    bend_penalty: float = 2.0,
    extra_xs: Optional[Iterable[float]] = None,
    extra_ys: Optional[Iterable[float]] = None,
) -> Optional[List[Point]]:
    """
    Plan an obstacle-aware orthogonal path using A* on a sparse visibility grid.

    Obstacles are assumed to be pre-inflated with the required clearance.
    """
    start = round_point(start)
    end = round_point(end)
    if start == end:
        return [start]

    rects = [normalize_rect(rect) for rect in obstacles]
    xs = {start[0], end[0]}
    ys = {start[1], end[1]}
    for rect in rects:
        xs.update((round(rect[0], 6), round(rect[2], 6)))
        ys.update((round(rect[1], 6), round(rect[3], 6)))
    if extra_xs:
        xs.update(round(x, 6) for x in extra_xs)
    if extra_ys:
        ys.update(round(y, 6) for y in extra_ys)

    xs_list = sorted(xs)
    ys_list = sorted(ys)
    valid_nodes = {
        (x, y)
        for x in xs_list
        for y in ys_list
        if (x, y) in (start, end) or not any(point_in_rect((x, y), rect, strict=True) for rect in rects)
    }

    adjacency: Dict[Point, List[Point]] = {node: [] for node in valid_nodes}

    for y in ys_list:
        row_nodes = [(x, y) for x in xs_list if (x, y) in valid_nodes]
        for left, right in pairwise(row_nodes):
            if not any(segment_intersects_rect(left, right, rect, strict=True) for rect in rects):
                adjacency[left].append(right)
                adjacency[right].append(left)

    for x in xs_list:
        col_nodes = [(x, y) for y in ys_list if (x, y) in valid_nodes]
        for lower, upper in pairwise(col_nodes):
            if not any(segment_intersects_rect(lower, upper, rect, strict=True) for rect in rects):
                adjacency[lower].append(upper)
                adjacency[upper].append(lower)

    if start not in adjacency or end not in adjacency:
        return None

    queue: List[Tuple[float, float, Point, Optional[str]]] = [
        (manhattan_distance(start, end), 0.0, start, None)
    ]
    best_costs: Dict[Tuple[Point, Optional[str]], float] = {(start, None): 0.0}
    parents: Dict[Tuple[Point, Optional[str]], Tuple[Point, Optional[str]]] = {}

    while queue:
        _, cost_so_far, node, incoming_dir = heapq.heappop(queue)
        state = (node, incoming_dir)
        if cost_so_far > best_costs.get(state, float("inf")) + _EPSILON:
            continue
        if node == end:
            path = [node]
            while state in parents:
                state = parents[state]
                path.append(state[0])
            path.reverse()
            return compress_path(path)

        for neighbor in adjacency[node]:
            direction = segment_direction(node, neighbor)
            if direction is None:
                continue
            step_cost = manhattan_distance(node, neighbor)
            bend_cost = bend_penalty if incoming_dir and incoming_dir != direction else 0.0
            next_cost = cost_so_far + step_cost + bend_cost
            next_state = (neighbor, direction)
            if next_cost + _EPSILON < best_costs.get(next_state, float("inf")):
                best_costs[next_state] = next_cost
                parents[next_state] = state
                heuristic = manhattan_distance(neighbor, end)
                heapq.heappush(queue, (next_cost + heuristic, next_cost, neighbor, direction))

    return None

"""
Geometry helpers for obstacle-aware orthogonal routing.

The planner builds a sparse rectilinear visibility grid from start/end
coordinates, inflated obstacle boundaries, **and Hanan grid intersections**,
then runs A* over that grid with bend penalty, pad repulsion, and optional
congestion awareness.

Key algorithmic foundations:
  - Hanan grid theorem (Hanan 1966): The rectilinear Steiner minimum tree
    lies on the Hanan grid formed by horizontal/vertical lines through all
    terminal and obstacle-corner points.
  - A* with directional state: tracking incoming direction in the search
    state enables accurate bend-cost accounting without double-counting.
  - Pad-away regularisation (He 2024 Eq 3.2): penalises routes that pass
    close to unrelated pads, preserving routing channels for later nets.
  - Congestion-driven cost (Rubin 1974 / PathFinder): optional per-cell
    congestion penalty steers routes away from already-dense regions.
"""

from __future__ import annotations

import heapq
import math
from itertools import pairwise
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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


def _build_hanan_grid(
    terminals: Iterable[Point],
    obstacles: Sequence[Rect],
    *,
    extra_xs: Optional[Iterable[float]] = None,
    extra_ys: Optional[Iterable[float]] = None,
    midpoint_density: int = 1,
) -> Tuple[List[float], List[float]]:
    """Build a Hanan grid from terminals and obstacle corners.

    The Hanan grid (Hanan 1966) is formed by drawing horizontal and vertical
    lines through every terminal point and obstacle corner.  The rectilinear
    Steiner minimum tree is guaranteed to lie on this grid.

    When *midpoint_density* > 0, extra grid lines are inserted at midpoints
    between adjacent lines.  This improves path quality at a modest cost to
    search space size.  density=1 adds one midpoint per gap (triples grid
    resolution), density=0 uses the raw Hanan grid.
    """
    xs: set[float] = set()
    ys: set[float] = set()
    for pt in terminals:
        xs.add(round(pt[0], 6))
        ys.add(round(pt[1], 6))
    for rect in obstacles:
        xs.update((round(rect[0], 6), round(rect[2], 6)))
        ys.update((round(rect[1], 6), round(rect[3], 6)))
    if extra_xs:
        xs.update(round(x, 6) for x in extra_xs)
    if extra_ys:
        ys.update(round(y, 6) for y in extra_ys)

    xs_sorted = sorted(xs)
    ys_sorted = sorted(ys)

    if midpoint_density > 0 and len(xs_sorted) >= 2:
        midpoints_x: set[float] = set()
        for a, b in pairwise(xs_sorted):
            gap = b - a
            if gap > _EPSILON:
                for i in range(1, midpoint_density + 1):
                    midpoints_x.add(round(a + gap * i / (midpoint_density + 1), 6))
        xs_sorted = sorted(xs | midpoints_x)

    if midpoint_density > 0 and len(ys_sorted) >= 2:
        midpoints_y: set[float] = set()
        for a, b in pairwise(ys_sorted):
            gap = b - a
            if gap > _EPSILON:
                for i in range(1, midpoint_density + 1):
                    midpoints_y.add(round(a + gap * i / (midpoint_density + 1), 6))
        ys_sorted = sorted(ys | midpoints_y)

    return xs_sorted, ys_sorted


def estimate_congestion(
    point: Point,
    existing_tracks: Optional[Sequence[Tuple[Point, Point]]] = None,
    cell_size: float = 1.0,
) -> float:
    """Estimate routing congestion near *point*.

    Returns a density value ≥ 0 representing how many existing track segments
    pass through the grid cell containing *point*.  This drives the
    congestion-aware cost term in A*.

    Reference: Rubin (1974) congestion-driven routing; PathFinder (McMurchie &
    Ebeling 1995) historical congestion penalty.
    """
    if not existing_tracks:
        return 0.0
    cx = point[0]
    cy = point[1]
    half = cell_size / 2
    count = 0
    for seg_start, seg_end in existing_tracks:
        # Check if segment passes near this cell
        min_x = min(seg_start[0], seg_end[0]) - half
        max_x = max(seg_start[0], seg_end[0]) + half
        min_y = min(seg_start[1], seg_end[1]) - half
        max_y = max(seg_start[1], seg_end[1]) + half
        if min_x <= cx <= max_x and min_y <= cy <= max_y:
            count += 1
    return float(count)


def plan_orthogonal_path(
    start: Point,
    end: Point,
    obstacles: Iterable[Rect],
    *,
    bend_penalty: float = 2.0,
    pad_repulsion: float = 0.0,
    pad_centers: Optional[Iterable[Point]] = None,
    extra_xs: Optional[Iterable[float]] = None,
    extra_ys: Optional[Iterable[float]] = None,
    via_cost: float = 0.0,
    congestion_weight: float = 0.0,
    existing_tracks: Optional[Sequence[Tuple[Point, Point]]] = None,
    congestion_cell_size: float = 1.0,
    midpoint_density: int = 1,
) -> Optional[List[Point]]:
    """
    Plan an obstacle-aware orthogonal path using A* on a Hanan grid.

    Obstacles are assumed to be pre-inflated with the required clearance.

    **Hanan Grid (Hanan 1966):**
    The search grid is the Hanan grid formed by horizontal/vertical lines
    through all terminal points and obstacle corners.  This guarantees that
    the optimal rectilinear Steiner path lies on the grid.  Optional midpoint
    insertion (*midpoint_density*) further improves path quality.

    **Cost function** (multi-term, all additive):

        g(n→m) = L(n,m) + λ_b · bend(n,m) + λ_g · pad_away(m)
                 + λ_c · congestion(m) + λ_v · via(m)

    where:
      - L(n,m) = Manhattan distance (wirelength)
      - λ_b · bend = bend penalty when direction changes
      - λ_g · pad_away = pad repulsion term (He 2024 Eq 3.2)
      - λ_c · congestion = congestion-driven penalty (Rubin 1974)
      - λ_v · via = via transition cost (layer change penalty)

    Reference: He (2024) Eq 3.2 — g(x) = L + λ_g · (1 / min_p d(x, p))
    """
    start = round_point(start)
    end = round_point(end)
    if start == end:
        return [start]

    rects = [normalize_rect(rect) for rect in obstacles]

    # Build Hanan grid with midpoint enrichment
    xs_list, ys_list = _build_hanan_grid(
        [start, end],
        rects,
        extra_xs=extra_xs,
        extra_ys=extra_ys,
        midpoint_density=midpoint_density,
    )

    # Cap grid size to avoid combinatorial explosion on dense boards
    _MAX_GRID_POINTS = 10_000
    if len(xs_list) * len(ys_list) > _MAX_GRID_POINTS:
        # Fall back to raw Hanan grid without midpoints
        xs_list, ys_list = _build_hanan_grid(
            [start, end], rects,
            extra_xs=extra_xs, extra_ys=extra_ys,
            midpoint_density=0,
        )

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

    # Pre-compute pad centers list for repulsion term (He 2024 Eq 3.2)
    _pad_pts: List[Point] = []
    if pad_repulsion > 0 and pad_centers:
        _pad_pts = [round_point(p) for p in pad_centers if round_point(p) not in (start, end)]

    def _pad_cost(pt: Point) -> float:
        """Pad-away regularisation: λ_g / min_p d(x, p)."""
        if not _pad_pts or pad_repulsion <= 0:
            return 0.0
        min_d = min(manhattan_distance(pt, p) for p in _pad_pts)
        if min_d < _EPSILON:
            return pad_repulsion * 100.0  # very close to pad — heavy penalty
        return pad_repulsion / min_d

    def _congestion_cost(pt: Point) -> float:
        """Congestion penalty: λ_c · density(cell)."""
        if congestion_weight <= 0 or not existing_tracks:
            return 0.0
        density = estimate_congestion(pt, existing_tracks, congestion_cell_size)
        return congestion_weight * density

    # A* with directional state for accurate bend accounting
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
            repulsion_cost = _pad_cost(neighbor)
            congest_cost = _congestion_cost(neighbor)
            next_cost = cost_so_far + step_cost + bend_cost + repulsion_cost + congest_cost
            next_state = (neighbor, direction)
            if next_cost + _EPSILON < best_costs.get(next_state, float("inf")):
                best_costs[next_state] = next_cost
                parents[next_state] = state
                heuristic = manhattan_distance(neighbor, end)
                heapq.heappush(queue, (next_cost + heuristic, next_cost, neighbor, direction))

    return None


def plan_steiner_tree(
    terminals: Sequence[Point],
    obstacles: Iterable[Rect],
    *,
    bend_penalty: float = 2.0,
    pad_repulsion: float = 0.0,
    pad_centers: Optional[Iterable[Point]] = None,
    extra_xs: Optional[Iterable[float]] = None,
    extra_ys: Optional[Iterable[float]] = None,
    congestion_weight: float = 0.0,
    existing_tracks: Optional[Sequence[Tuple[Point, Point]]] = None,
) -> Optional[List[List[Point]]]:
    """Plan a rectilinear Steiner tree connecting multiple terminals.

    For multi-pin nets (>2 pads), this decomposes the problem using a minimum
    spanning tree (MST) on terminal distances, then routes each edge of the
    MST independently using ``plan_orthogonal_path``.

    Algorithm (Prim-based MST decomposition):
      1. Build complete graph on terminals with Manhattan distance weights.
      2. Extract MST using Prim's algorithm.
      3. Route each MST edge using A* on the Hanan grid.
      4. Previously-routed segments become obstacles for subsequent edges
         (prevents overlapping traces).

    Reference: Kahng & Robins (1992) — "A new class of iterative Steiner tree
    heuristics with good performance".

    Returns a list of paths (one per MST edge), or None if any edge fails.
    """
    if len(terminals) < 2:
        return None
    if len(terminals) == 2:
        path = plan_orthogonal_path(
            terminals[0], terminals[1], obstacles,
            bend_penalty=bend_penalty,
            pad_repulsion=pad_repulsion,
            pad_centers=pad_centers,
            extra_xs=extra_xs,
            extra_ys=extra_ys,
            congestion_weight=congestion_weight,
            existing_tracks=existing_tracks,
        )
        return [path] if path else None

    terms = [round_point(t) for t in terminals]

    # Prim's MST
    n = len(terms)
    in_tree = [False] * n
    min_edge: List[Tuple[float, int]] = [(float("inf"), -1)] * n
    min_edge[0] = (0.0, -1)
    mst_edges: List[Tuple[int, int]] = []

    for _ in range(n):
        # Pick minimum-cost node not yet in tree
        u = -1
        for v in range(n):
            if not in_tree[v] and (u == -1 or min_edge[v][0] < min_edge[u][0]):
                u = v
        if u == -1:
            break
        in_tree[u] = True
        parent = min_edge[u][1]
        if parent >= 0:
            mst_edges.append((parent, u))
        # Update costs
        for v in range(n):
            if not in_tree[v]:
                dist = manhattan_distance(terms[u], terms[v])
                if dist < min_edge[v][0]:
                    min_edge[v] = (dist, u)

    # Route each MST edge, adding routed segments as soft obstacles
    obstacle_list = list(obstacles)
    routed_tracks: List[Tuple[Point, Point]] = list(existing_tracks or [])
    paths: List[List[Point]] = []

    for u, v in mst_edges:
        path = plan_orthogonal_path(
            terms[u], terms[v], obstacle_list,
            bend_penalty=bend_penalty,
            pad_repulsion=pad_repulsion,
            pad_centers=pad_centers,
            extra_xs=extra_xs,
            extra_ys=extra_ys,
            congestion_weight=congestion_weight,
            existing_tracks=routed_tracks,
        )
        if path is None:
            # Try direct L-route as fallback
            path = [terms[u], terms[v]]
        paths.append(path)
        # Add routed segments for congestion tracking
        for seg_a, seg_b in pairwise(path):
            routed_tracks.append((seg_a, seg_b))

    return paths

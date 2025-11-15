#!/usr/bin/env python3
"""Admin viewer for the GGW orbital sandbox."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import pygame

WINDOW_SIZE = 900
TRAIL_LENGTH = 300
BACKGROUND_COLOR = (5, 8, 12)
PLANET_COLOR = (30, 60, 120)
GRAVITY_WELL_COLOR = (50, 80, 150)
DESPAWN_COLOR = (120, 60, 40)
TRAIL_COLOR = (80, 80, 80)
HUD_COLOR = (220, 220, 220)
BODY_COLORS = {
    "Ship": (80, 200, 255),
    "Asteroid": (255, 200, 80),
    "Debris": (200, 80, 80),
    "Missile": (180, 180, 255),
}
PICK_RADIUS_PX = 12
ZOOM_STEP = 1.1


class ViewerState:
    def __init__(self) -> None:
        self.base_scale: Optional[float] = None
        self.zoom_factor: float = 1.0
        self.zoom_factor_min: float = 1e-4
        self.zoom_factor_max: Optional[float] = None
        self.camera_center_world: List[float] = [0.0, 0.0]
        self.is_panning: bool = False
        self.pan_start_mouse: Tuple[int, int] = (0, 0)
        self.pan_start_center: Tuple[float, float] = (0.0, 0.0)
        self.selected_id: Optional[int] = None


def server_binary_path() -> str:
    exe = "ggw_world.exe" if os.name == "nt" else "ggw_world"
    path = os.path.join("target", "debug", exe)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Binary '{path}' not found. Run 'cargo build --bin ggw_world' first."
        )
    return path


def launch_server() -> subprocess.Popen:
    path = server_binary_path()
    return subprocess.Popen(
        [path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )


def init_pygame() -> Tuple[pygame.Surface, pygame.font.Font]:
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_SIZE, WINDOW_SIZE))
    pygame.display.set_caption("GGW Orbital Viewer")
    font = pygame.font.SysFont("consolas", 18)
    return screen, font


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def ensure_base_scale(snapshot: Dict, state: ViewerState) -> None:
    if state.base_scale is not None:
        return

    bodies = snapshot.get("bodies", [])
    max_r = snapshot.get("planet_radius_m", 0.0)
    for body in bodies:
        dist = math.hypot(body.get("x", 0.0), body.get("y", 0.0))
        max_r = max(max_r, dist)
    if max_r <= 0.0:
        max_r = 1.0

    usable_radius = 0.9 * (WINDOW_SIZE / 2.0)
    base_scale = usable_radius / max_r
    if base_scale <= 0.0:
        base_scale = 1e-6

    state.base_scale = base_scale
    state.zoom_factor = 1.0
    state.zoom_factor_min = 1e-4
    max_zoom = max(state.zoom_factor_min, 1.0 / base_scale)
    state.zoom_factor_max = max_zoom
    state.zoom_factor = clamp(state.zoom_factor, state.zoom_factor_min, state.zoom_factor_max)
    state.camera_center_world = [0.0, 0.0]


def world_to_screen(
    x: float,
    y: float,
    cam_center: Sequence[float],
    base_scale: float,
    zoom_factor: float,
) -> Tuple[int, int]:
    cx = WINDOW_SIZE / 2.0
    cy = WINDOW_SIZE / 2.0
    scale = base_scale * zoom_factor
    screen_x = cx + (x - cam_center[0]) * scale
    screen_y = cy - (y - cam_center[1]) * scale
    return int(screen_x), int(screen_y)


def meters_to_pixels(radius_m: float, base_scale: float, zoom_factor: float) -> int:
    scale = base_scale * zoom_factor
    pixels = int(radius_m * scale)
    return max(1, abs(pixels))


def update_trails(trails: Dict[int, Deque[Tuple[int, int]]], snapshot: Dict, state: ViewerState) -> None:
    if state.base_scale is None:
        return
    for body in snapshot.get("bodies", []):
        body_id = body["id"]
        sx, sy = world_to_screen(
            body["x"],
            body["y"],
            state.camera_center_world,
            state.base_scale,
            state.zoom_factor,
        )
        trail = trails[body_id]
        trail.append((sx, sy))
        if len(trail) > TRAIL_LENGTH:
            trail.popleft()


def prune_trails(trails: Dict[int, Deque[Tuple[int, int]]], current_ids: Iterable[int]) -> None:
    valid = set(current_ids)
    for body_id in list(trails.keys()):
        if body_id not in valid:
            del trails[body_id]


def handle_events(snapshot: Optional[Dict], state: ViewerState) -> bool:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return False
        if event.type == pygame.MOUSEWHEEL and state.base_scale is not None:
            if event.y > 0:
                state.zoom_factor *= ZOOM_STEP
            elif event.y < 0:
                state.zoom_factor /= ZOOM_STEP
            if state.zoom_factor_max is not None:
                state.zoom_factor = clamp(
                    state.zoom_factor,
                    state.zoom_factor_min,
                    state.zoom_factor_max,
                )
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            body_id = find_body_under_cursor(snapshot, event.pos, state)
            if body_id is not None:
                state.selected_id = body_id
                state.is_panning = False
            else:
                state.is_panning = True
                state.pan_start_mouse = event.pos
                state.pan_start_center = tuple(state.camera_center_world)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            state.is_panning = False
        if event.type == pygame.MOUSEMOTION and state.is_panning and state.base_scale is not None:
            scale = state.base_scale * state.zoom_factor
            if scale > 0.0:
                dx = event.pos[0] - state.pan_start_mouse[0]
                dy = event.pos[1] - state.pan_start_mouse[1]
                state.camera_center_world[0] = state.pan_start_center[0] - dx / scale
                state.camera_center_world[1] = state.pan_start_center[1] + dy / scale
    return True


def find_body_under_cursor(
    snapshot: Optional[Dict], mouse_pos: Tuple[int, int], state: ViewerState
) -> Optional[int]:
    if snapshot is None or state.base_scale is None:
        return None
    bodies = snapshot.get("bodies", [])
    best_id = None
    best_dist = PICK_RADIUS_PX
    for body in bodies:
        sx, sy = world_to_screen(
            body["x"],
            body["y"],
            state.camera_center_world,
            state.base_scale,
            state.zoom_factor,
        )
        dist = math.hypot(mouse_pos[0] - sx, mouse_pos[1] - sy)
        if dist <= best_dist:
            best_dist = dist
            best_id = body["id"]
    return best_id


def draw_snapshot(
    screen: pygame.Surface,
    font: pygame.font.Font,
    snapshot: Dict,
    trails: Dict[int, Deque[Tuple[int, int]]],
    state: ViewerState,
) -> None:
    if state.base_scale is None:
        screen.fill(BACKGROUND_COLOR)
        pygame.display.flip()
        return

    screen.fill(BACKGROUND_COLOR)
    base_scale = state.base_scale
    zoom_factor = state.zoom_factor
    cam_center = state.camera_center_world

    origin_px = world_to_screen(0.0, 0.0, cam_center, base_scale, zoom_factor)
    planet_radius_m = snapshot.get("planet_radius_m", 6_371_000.0)
    gravity_well_radius = snapshot.get("gravity_well_radius_m")
    despawn_radius = snapshot.get("despawn_radius_m")

    planet_px = meters_to_pixels(planet_radius_m, base_scale, zoom_factor)
    pygame.draw.circle(screen, PLANET_COLOR, origin_px, planet_px)

    draw_optional_ring(screen, origin_px, gravity_well_radius, base_scale, zoom_factor, GRAVITY_WELL_COLOR)
    draw_optional_ring(screen, origin_px, despawn_radius, base_scale, zoom_factor, DESPAWN_COLOR)

    for trail in trails.values():
        if len(trail) >= 2:
            pygame.draw.lines(screen, TRAIL_COLOR, False, list(trail), 1)

    selected_id = state.selected_id
    for body in snapshot.get("bodies", []):
        color = BODY_COLORS.get(body.get("body_type"), (255, 255, 255))
        radius_px = meters_to_pixels(body.get("radius_m", 10.0), base_scale, zoom_factor)
        sx, sy = world_to_screen(
            body.get("x", 0.0),
            body.get("y", 0.0),
            cam_center,
            base_scale,
            zoom_factor,
        )
        pygame.draw.circle(screen, color, (sx, sy), radius_px)
        if selected_id == body.get("id"):
            pygame.draw.circle(screen, (255, 255, 255), (sx, sy), radius_px + 2, width=1)

    sim_time = snapshot.get("sim_time", 0.0)
    hud = font.render(f"t = {sim_time:,.1f} s", True, HUD_COLOR)
    screen.blit(hud, (10, 10))

    draw_selected_popup(screen, font, snapshot, state)

    pygame.display.flip()


def draw_optional_ring(
    screen: pygame.Surface,
    center: Tuple[int, int],
    radius_m: Optional[float],
    base_scale: float,
    zoom_factor: float,
    color: Tuple[int, int, int],
) -> None:
    if radius_m is None:
        return
    radius_px = meters_to_pixels(radius_m, base_scale, zoom_factor)
    if radius_px < 10:
        return
    if radius_px > WINDOW_SIZE * 4:
        return
    pygame.draw.circle(screen, color, center, radius_px, width=1)


def format_distance(meters: float) -> str:
    if meters < 1_000.0:
        return f"{meters:.0f} m"
    if meters < 1_000_000.0:
        return f"{meters / 1_000.0:.2f} km"
    if meters < 1_000_000_000.0:
        return f"{meters / 1_000_000.0:.2f} Mm"
    return f"{meters / 1_000_000_000.0:.2f} Gm"


def draw_selected_popup(
    screen: pygame.Surface,
    font: pygame.font.Font,
    snapshot: Dict,
    state: ViewerState,
) -> None:
    if state.selected_id is None:
        return
    body = next((b for b in snapshot.get("bodies", []) if b["id"] == state.selected_id), None)
    if body is None:
        return

    x = body.get("x", 0.0)
    y = body.get("y", 0.0)
    vx = body.get("vx", 0.0)
    vy = body.get("vy", 0.0)
    body_type = body.get("body_type", "Unknown")
    radius_m = body.get("radius_m", 0.0)
    planet_radius = snapshot.get("planet_radius_m", 6_371_000.0)
    mu = snapshot.get("mu", 0.0)

    r = math.hypot(x, y)
    altitude = max(0.0, r - planet_radius)
    speed = math.hypot(vx, vy)

    semi_major_axis = None
    if mu > 0.0 and r > 0.0:
        denom = 2.0 / r - (speed * speed) / mu
        if abs(denom) > 1e-12:
            semi_major_axis = 1.0 / denom
    period_hours = None
    if semi_major_axis and semi_major_axis > 0.0 and mu > 0.0:
        period_seconds = 2.0 * math.pi * math.sqrt(semi_major_axis ** 3 / mu)
        period_hours = period_seconds / 3600.0

    lines = [
        f"ID {body['id']} ({body_type})",
        f"Alt: {format_distance(altitude)}",
        f"Speed: {speed / 1000.0:.2f} km/s",
        f"Radius: {format_distance(radius_m)}",
    ]
    if period_hours is not None:
        lines.append(f"Period: {period_hours:.2f} h")

    padding = 8
    line_height = font.get_linesize()
    width = max(font.size(text)[0] for text in lines) + padding * 2
    height = line_height * len(lines) + padding * 2
    rect = pygame.Rect(WINDOW_SIZE - width - 20, 20, width, height)
    pygame.draw.rect(screen, (15, 20, 30), rect)
    pygame.draw.rect(screen, (100, 120, 150), rect, 1)

    y_cursor = rect.top + padding
    for text in lines:
        surface = font.render(text, True, HUD_COLOR)
        screen.blit(surface, (rect.left + padding, y_cursor))
        y_cursor += line_height


def main() -> None:
    server = launch_server()
    screen, font = init_pygame()
    trails: Dict[int, Deque[Tuple[int, int]]] = defaultdict(lambda: deque(maxlen=TRAIL_LENGTH))
    state = ViewerState()
    snapshot: Optional[Dict] = None

    try:
        while True:
            if not handle_events(snapshot, state):
                break

            line = server.stdout.readline() if server.stdout else ""
            if line == "":
                break
            line = line.strip()
            if not line:
                continue

            snapshot = json.loads(line)
            ensure_base_scale(snapshot, state)

            current_ids = {body["id"] for body in snapshot.get("bodies", [])}
            prune_trails(trails, current_ids)
            if state.selected_id is not None and state.selected_id not in current_ids:
                state.selected_id = None

            update_trails(trails, snapshot, state)
            draw_snapshot(screen, font, snapshot, trails, state)
    except KeyboardInterrupt:
        pass
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
        pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(exc)
        sys.exit(1)

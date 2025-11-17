#!/usr/bin/env python3
"""Admin viewer for the GGW orbital sandbox."""

from __future__ import annotations

import json
import math
import socket
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import pygame

WINDOW_WIDTH = 900
WINDOW_HEIGHT = 900
TRAIL_LENGTH = 300
PICK_RADIUS_PX = 12
ZOOM_STEP = 1.1
HUD_MARGIN = 12
HULL_SHAPE_MIN_PX = 18
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 40000

# CRT-inspired styling
COLORS = {
    "bg": (2, 5, 3),
    "planet_fill": (6, 20, 10),
    "planet_outline": (0, 180, 90),
    "fg_main": (0, 255, 102),
    "fg_dim": (0, 138, 63),
    "fg_highlight": (182, 255, 201),
    "fg_warn": (255, 176, 0),
    "trail": (0, 100, 50),
    "info_bg": (10, 16, 12),
    "info_border": (0, 120, 60),
    "ring_gravity": (0, 80, 50),
    "ring_despawn": (60, 90, 30),
}

BODY_COLORS = {
    "Ship": COLORS["fg_main"],
    "Asteroid": (0, 200, 120),
    "Debris": (80, 220, 150),
    "Missile": (0, 255, 170),
}

FONT_NAME = "consolas"
FONT_SMALL_SIZE = 18
FONT_MEDIUM_SIZE = 20
FONT_SMALL: Optional[pygame.font.Font] = None
FONT_MEDIUM: Optional[pygame.font.Font] = None

SIM_SPEED_KEYS = {
    pygame.K_0: 0.0,
    pygame.K_1: 1.0,
    pygame.K_2: 10.0,
    pygame.K_3: 60.0,
    pygame.K_4: 600.0,
}


class ViewerState:
    def __init__(self) -> None:
        self.base_scale: Optional[float] = None
        self.zoom_factor: float = 1.0
        self.zoom_factor_min: float = 1e-4
        self.zoom_factor_max: Optional[float] = None
        self.camera_center_world: List[float] = [0.0, 0.0]
        self.camera_follow: bool = False
        self.camera_offset: List[float] = [0.0, 0.0]
        self.is_panning: bool = False
        self.pan_start_mouse: Tuple[int, int] = (0, 0)
        self.pan_start_center: Tuple[float, float] = (0.0, 0.0)
        self.pan_start_offset: Tuple[float, float] = (0.0, 0.0)
        self.selected_id: Optional[int] = None
        self.selected_planet: bool = False
        self.sim_speed: float = 1.0


class ServerConnection:
    def __init__(self) -> None:
        self.addr = (SERVER_HOST, SERVER_PORT)
        self.sock: Optional[socket.socket] = None
        self.sock_file = None
        self.connect()

    def connect(self) -> None:
        while True:
            try:
                sock = socket.create_connection(self.addr)
            except OSError:
                print(
                    "Could not connect to GGW server at 127.0.0.1:40000, retrying...",
                    flush=True,
                )
                time.sleep(1.0)
                continue
            self.sock = sock
            self.sock_file = sock.makefile("r", encoding="utf-8")
            print("Connected to GGW server.", flush=True)
            break

    def close(self) -> None:
        if self.sock_file is not None:
            try:
                self.sock_file.close()
            except OSError:
                pass
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.sock_file = None

    def readline(self) -> str:
        while True:
            if self.sock_file is None:
                self.connect()
                continue
            try:
                line = self.sock_file.readline()
            except OSError:
                self.close()
                continue
            if line == "":
                print("Connection to GGW server lost, reconnecting...", flush=True)
                self.close()
                continue
            return line

    def send_json(self, payload: Dict[str, Any]) -> None:
        data = (json.dumps(payload) + "\n").encode("utf-8")
        while True:
            if self.sock is None:
                self.connect()
            try:
                assert self.sock is not None
                self.sock.sendall(data)
                return
            except OSError:
                print("Send failed, reconnecting to GGW server...", flush=True)
                self.close()


def init_pygame() -> pygame.Surface:
    global WINDOW_WIDTH, WINDOW_HEIGHT, FONT_SMALL, FONT_MEDIUM

    pygame.init()
    info = pygame.display.Info()
    WINDOW_WIDTH, WINDOW_HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.FULLSCREEN)
    pygame.display.set_caption("GGW Orbital Viewer")
    FONT_SMALL = pygame.font.SysFont(FONT_NAME, FONT_SMALL_SIZE)
    FONT_MEDIUM = pygame.font.SysFont(FONT_NAME, FONT_MEDIUM_SIZE)
    return screen


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

    usable_radius = 0.9 * (min(WINDOW_WIDTH, WINDOW_HEIGHT) / 2.0)
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
    cx = WINDOW_WIDTH / 2.0
    cy = WINDOW_HEIGHT / 2.0
    scale = base_scale * zoom_factor
    screen_x = cx + (x - cam_center[0]) * scale
    screen_y = cy - (y - cam_center[1]) * scale
    return int(screen_x), int(screen_y)


def screen_to_world(
    sx: float,
    sy: float,
    cam_center: Sequence[float],
    base_scale: float,
    zoom_factor: float,
) -> Tuple[float, float]:
    cx = WINDOW_WIDTH / 2.0
    cy = WINDOW_HEIGHT / 2.0
    scale = base_scale * zoom_factor
    if scale == 0.0:
        return cam_center[0], cam_center[1]
    wx = cam_center[0] + (sx - cx) / scale
    wy = cam_center[1] - (sy - cy) / scale
    return wx, wy


def meters_to_pixels(radius_m: float, base_scale: float, zoom_factor: float) -> int:
    scale = base_scale * zoom_factor
    pixels = int(radius_m * scale)
    return max(1, abs(pixels))


def update_trails(trails: Dict[int, Deque[Tuple[float, float]]], snapshot: Dict) -> None:
    for body in snapshot.get("bodies", []):
        body_id = body["id"]
        trail = trails[body_id]
        trail.append((body.get("x", 0.0), body.get("y", 0.0)))
        if len(trail) > TRAIL_LENGTH:
            trail.popleft()


def update_camera_center(snapshot: Dict, state: ViewerState) -> None:
    if not state.camera_follow or state.selected_id is None:
        return
    body = find_body_by_id(snapshot, state.selected_id)
    if body is None:
        state.camera_follow = False
        return
    state.camera_center_world[0] = body.get("x", 0.0) + state.camera_offset[0]
    state.camera_center_world[1] = body.get("y", 0.0) + state.camera_offset[1]


def prune_trails(
    trails: Dict[int, Deque[Tuple[float, float]]],
    current_ids: Iterable[int],
    state: ViewerState,
) -> None:
    valid = set(current_ids)
    for body_id in list(trails.keys()):
        if body_id not in valid:
            del trails[body_id]
    if state.selected_id is not None and state.selected_id not in valid:
        state.selected_id = None
        state.camera_follow = False
        state.camera_offset = [0.0, 0.0]


def send_time_scale_command(conn: ServerConnection, time_scale: float) -> None:
    conn.send_json({"type": "set_time_scale", "time_scale": time_scale})


def set_sim_speed(conn: ServerConnection, state: ViewerState, new_speed: float) -> None:
    state.sim_speed = new_speed
    send_time_scale_command(conn, new_speed)


def handle_events(
    snapshot: Optional[Dict], state: ViewerState, conn: ServerConnection
) -> bool:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return False
            if event.key in SIM_SPEED_KEYS:
                set_sim_speed(conn, state, SIM_SPEED_KEYS[event.key])
        if event.type == pygame.MOUSEWHEEL and state.base_scale is not None:
            if event.y > 0:
                state.zoom_factor *= ZOOM_STEP
            elif event.y < 0:
                state.zoom_factor /= ZOOM_STEP
            state.zoom_factor = max(state.zoom_factor, state.zoom_factor_min)
            if state.zoom_factor_max is not None:
                state.zoom_factor = min(state.zoom_factor, state.zoom_factor_max)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not attempt_selection(snapshot, state, event.pos):
                clear_selection(state)
                state.is_panning = True
                state.pan_start_mouse = event.pos
                state.pan_start_center = tuple(state.camera_center_world)
                state.pan_start_offset = tuple(state.camera_offset)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            state.is_panning = False
        if event.type == pygame.MOUSEMOTION and state.is_panning and state.base_scale is not None:
            scale = state.base_scale * state.zoom_factor
            if scale > 0.0:
                dx = event.pos[0] - state.pan_start_mouse[0]
                dy = event.pos[1] - state.pan_start_mouse[1]
                if state.camera_follow:
                    state.camera_offset[0] = state.pan_start_offset[0] - dx / scale
                    state.camera_offset[1] = state.pan_start_offset[1] + dy / scale
                else:
                    state.camera_center_world[0] = (
                        state.pan_start_center[0] - dx / scale
                    )
                    state.camera_center_world[1] = (
                        state.pan_start_center[1] + dy / scale
                    )
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


def find_body_by_id(snapshot: Dict, body_id: int) -> Optional[Dict]:
    for body in snapshot.get("bodies", []):
        if body.get("id") == body_id:
            return body
    return None


def clear_selection(state: ViewerState) -> None:
    state.selected_planet = False
    state.selected_id = None
    state.camera_follow = False
    state.camera_offset = [0.0, 0.0]


def attempt_selection(snapshot: Optional[Dict], state: ViewerState, mouse_pos: Tuple[int, int]) -> bool:
    if snapshot is None or state.base_scale is None:
        return False

    planet_radius = snapshot.get("planet_radius_m", 0.0)
    wx, wy = screen_to_world(
        mouse_pos[0],
        mouse_pos[1],
        state.camera_center_world,
        state.base_scale,
        state.zoom_factor,
    )
    distance = math.hypot(wx, wy)
    if planet_radius > 0.0 and distance <= planet_radius * 1.02:
        state.selected_planet = True
        state.selected_id = None
        state.camera_follow = False
        state.camera_offset = [0.0, 0.0]
        state.camera_center_world = [0.0, 0.0]
        state.is_panning = False
        return True

    body_id = find_body_under_cursor(snapshot, mouse_pos, state)
    if body_id is not None:
        body = find_body_by_id(snapshot, body_id)
        if body is not None:
            state.selected_planet = False
            state.selected_id = body_id
            state.camera_follow = True
            state.camera_offset = [0.0, 0.0]
            state.camera_center_world = [
                body.get("x", 0.0),
                body.get("y", 0.0),
            ]
            state.is_panning = False
            return True
    return False


def draw_snapshot(
    screen: pygame.Surface,
    snapshot: Dict,
    trails: Dict[int, Deque[Tuple[float, float]]],
    state: ViewerState,
) -> None:
    if state.base_scale is None:
        screen.fill(COLORS["bg"])
        pygame.display.flip()
        return

    screen.fill(COLORS["bg"])
    base_scale = state.base_scale
    zoom_factor = state.zoom_factor
    cam_center = state.camera_center_world

    origin_px = world_to_screen(0.0, 0.0, cam_center, base_scale, zoom_factor)
    planet_radius_m = snapshot.get("planet_radius_m", 6_371_000.0)
    gravity_well_radius = snapshot.get("gravity_well_radius_m")
    despawn_radius = snapshot.get("despawn_radius_m")

    planet_px = meters_to_pixels(planet_radius_m, base_scale, zoom_factor)
    pygame.draw.circle(screen, COLORS["planet_fill"], origin_px, planet_px)
    pygame.draw.circle(screen, COLORS["planet_outline"], origin_px, planet_px, width=2)
    if state.selected_planet:
        pygame.draw.circle(
            screen,
            COLORS["fg_highlight"],
            origin_px,
            max(planet_px + 4, planet_px + 1),
            width=2,
        )

    draw_optional_ring(
        screen,
        origin_px,
        gravity_well_radius,
        base_scale,
        zoom_factor,
        COLORS["ring_gravity"],
    )
    draw_optional_ring(
        screen,
        origin_px,
        despawn_radius,
        base_scale,
        zoom_factor,
        COLORS["ring_despawn"],
    )

    for body_id, trail in trails.items():
        if len(trail) < 2:
            continue
        projected = [
            world_to_screen(wx, wy, cam_center, base_scale, zoom_factor)
            for wx, wy in trail
        ]
        color = COLORS["trail"]
        width = 1
        if state.selected_id == body_id:
            color = COLORS["fg_highlight"]
            width = 2
        pygame.draw.lines(screen, color, False, projected, width)

    selected_id = state.selected_id
    for body in snapshot.get("bodies", []):
        draw_body(screen, body, cam_center, base_scale, zoom_factor, selected_id)

    draw_hud(screen, snapshot, state)
    draw_info_panel(screen, snapshot, state)

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
    if radius_px > max(WINDOW_WIDTH, WINDOW_HEIGHT) * 4:
        return
    pygame.draw.circle(screen, color, center, radius_px, width=1)


def draw_body(
    screen: pygame.Surface,
    body: Dict,
    cam_center: Sequence[float],
    base_scale: float,
    zoom_factor: float,
    selected_id: Optional[int],
) -> None:
    body_id = body.get("id")
    body_type = body.get("body_type")
    color = BODY_COLORS.get(body_type, COLORS["fg_main"])
    radius_px = meters_to_pixels(body.get("radius_m", 10.0), base_scale, zoom_factor)
    hull = body.get("hull_shape")
    hull_drawn = False
    if hull and radius_px >= HULL_SHAPE_MIN_PX:
        vertices = hull.get("vertices", [])
        if len(vertices) >= 3:
            points = []
            bx = body.get("x", 0.0)
            by = body.get("y", 0.0)
            for vertex in vertices:
                wx = bx + vertex.get("x", 0.0)
                wy = by + vertex.get("y", 0.0)
                points.append(
                    world_to_screen(wx, wy, cam_center, base_scale, zoom_factor)
                )
            if len(points) >= 3:
                pygame.draw.polygon(screen, color, points, width=0)
                hull_drawn = True
                if selected_id == body_id:
                    pygame.draw.polygon(
                        screen, COLORS["fg_highlight"], points, width=2
                    )
    sx, sy = world_to_screen(
        body.get("x", 0.0),
        body.get("y", 0.0),
        cam_center,
        base_scale,
        zoom_factor,
    )
    if not hull_drawn:
        pygame.draw.circle(screen, color, (sx, sy), radius_px)
        if selected_id == body_id:
            pygame.draw.circle(screen, COLORS["fg_highlight"], (sx, sy), radius_px + 3, width=1)
            pygame.draw.circle(screen, COLORS["fg_highlight"], (sx, sy), radius_px + 6, width=1)
    else:
        center_radius = max(2, radius_px // 6)
        pygame.draw.circle(screen, COLORS["bg"], (sx, sy), center_radius)
        pygame.draw.circle(screen, color, (sx, sy), center_radius, width=1)


def format_distance(meters: float) -> str:
    if meters < 1_000.0:
        return f"{meters:.0f} m"
    if meters < 1_000_000.0:
        return f"{meters / 1_000.0:.2f} km"
    if meters < 1_000_000_000.0:
        return f"{meters / 1_000_000.0:.2f} Mm"
    return f"{meters / 1_000_000_000.0:.2f} Gm"


def draw_hud(screen: pygame.Surface, snapshot: Dict, state: ViewerState) -> None:
    if FONT_SMALL is None:
        return
    font = FONT_SMALL
    sim_time = snapshot.get("sim_time", 0.0)
    lines = [
        f"t = {sim_time:,.1f} s",
        f"sim dt = {state.sim_speed:.1f} s/step",
    ]
    x = HUD_MARGIN
    y = HUD_MARGIN
    for text in lines:
        surface = font.render(text, True, COLORS["fg_main"])
        screen.blit(surface, (x, y))
        y += font.get_linesize()


def draw_info_panel(screen: pygame.Surface, snapshot: Dict, state: ViewerState) -> None:
    info = build_selection_info(snapshot, state)
    if info is None or FONT_SMALL is None or FONT_MEDIUM is None:
        return

    title, lines = info
    padding = 10
    title_height = FONT_MEDIUM.get_linesize()
    body_height = FONT_SMALL.get_linesize()
    text_widths = [FONT_MEDIUM.size(title)[0]]
    text_widths.extend(FONT_SMALL.size(line)[0] for line in lines)
    width = max(text_widths) + padding * 2
    height = padding * 2 + title_height + body_height * len(lines)
    rect = pygame.Rect(WINDOW_WIDTH - width - HUD_MARGIN, HUD_MARGIN, width, height)
    pygame.draw.rect(screen, COLORS["info_bg"], rect)
    pygame.draw.rect(screen, COLORS["info_border"], rect, 1)

    y = rect.top + padding
    title_surface = FONT_MEDIUM.render(title, True, COLORS["fg_main"])
    screen.blit(title_surface, (rect.left + padding, y))
    y += title_height
    for line in lines:
        surface = FONT_SMALL.render(line, True, COLORS["fg_main"])
        screen.blit(surface, (rect.left + padding, y))
        y += body_height


def build_selection_info(snapshot: Dict, state: ViewerState) -> Optional[Tuple[str, List[str]]]:
    if state.selected_planet:
        planet_radius = snapshot.get("planet_radius_m", 6_371_000.0)
        gravity_well = snapshot.get("gravity_well_radius_m", planet_radius)
        despawn = snapshot.get("despawn_radius_m", gravity_well)
        lines = [
            f"Radius: {format_distance(planet_radius)}",
            f"Gravity well: {format_distance(gravity_well)}",
            f"Despawn: {format_distance(despawn)}",
        ]
        return "Planet", lines

    if state.selected_id is None:
        return None

    body = next((b for b in snapshot.get("bodies", []) if b["id"] == state.selected_id), None)
    if body is None:
        return None

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
        f"Alt: {format_distance(altitude)}",
        f"Speed: {speed / 1000.0:.2f} km/s",
        f"Radius: {format_distance(radius_m)}",
    ]
    if period_hours is not None:
        lines.append(f"Period: {period_hours:.2f} h")

    return f"ID {body['id']} ({body_type})", lines


def main() -> None:
    screen = init_pygame()
    conn = ServerConnection()
    trails: Dict[int, Deque[Tuple[float, float]]] = defaultdict(
        lambda: deque(maxlen=TRAIL_LENGTH)
    )
    state = ViewerState()
    snapshot: Optional[Dict] = None

    try:
        while True:
            if not handle_events(snapshot, state, conn):
                break

            line = conn.readline()
            line = line.strip()
            if not line:
                continue

            snapshot = json.loads(line)
            ensure_base_scale(snapshot, state)

            current_ids = {body["id"] for body in snapshot.get("bodies", [])}
            prune_trails(trails, current_ids, state)

            update_trails(trails, snapshot)
            update_camera_center(snapshot, state)
            draw_snapshot(screen, snapshot, trails, state)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
        pygame.quit()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Simple CRT-style viewer for the ship interior prototype."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

import pygame

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
TILE_MARGIN = 80
FONT_NAME = "consolas"
FONT_SMALL_SIZE = 20
FONT_MEDIUM_SIZE = 24

COLORS = {
    "bg": (2, 5, 3),
    "grid": (0, 60, 30),
    "floor": (10, 26, 15),
    "wall": (0, 160, 70),
    "bed": (0, 120, 80),
    "door": (0, 150, 80),
    "door_open": (0, 90, 45),
    "device": (0, 200, 120),
    "device_dim": (0, 120, 60),
    "pawn": (182, 255, 201),
    "hud_bg": (10, 16, 12),
    "hud_border": (0, 120, 60),
    "fg": (0, 255, 102),
    "fg_dim": (0, 138, 63),
}

MOVE_KEYS = {
    pygame.K_UP: (0, -1),
    pygame.K_DOWN: (0, 1),
    pygame.K_LEFT: (-1, 0),
    pygame.K_RIGHT: (1, 0),
    pygame.K_w: (0, -1),
    pygame.K_s: (0, 1),
    pygame.K_a: (-1, 0),
    pygame.K_d: (1, 0),
}

FONT_SMALL: Optional[pygame.font.Font] = None
FONT_MEDIUM: Optional[pygame.font.Font] = None


class ViewerState:
    def __init__(self) -> None:
        self.tile_size: Optional[int] = None
        self.offset: Tuple[int, int] = (0, 0)


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
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )


def init_pygame() -> pygame.Surface:
    global FONT_SMALL, FONT_MEDIUM

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("GGW Interior Viewer")
    FONT_SMALL = pygame.font.SysFont(FONT_NAME, FONT_SMALL_SIZE)
    FONT_MEDIUM = pygame.font.SysFont(FONT_NAME, FONT_MEDIUM_SIZE)
    return screen


def ensure_layout(snapshot: Dict, state: ViewerState) -> None:
    if state.tile_size is not None:
        return
    interior = snapshot.get("interior")
    if not interior:
        return
    width = max(1, interior.get("width", 1))
    height = max(1, interior.get("height", 1))
    usable_width = max(1, WINDOW_WIDTH - 2 * TILE_MARGIN)
    usable_height = max(1, WINDOW_HEIGHT - 2 * TILE_MARGIN)
    tile_w = usable_width / width
    tile_h = usable_height / height
    tile_size = int(min(tile_w, tile_h))
    if tile_size <= 0:
        tile_size = 16
    grid_w = tile_size * width
    grid_h = tile_size * height
    offset_x = (WINDOW_WIDTH - grid_w) // 2
    offset_y = (WINDOW_HEIGHT - grid_h) // 2
    state.tile_size = tile_size
    state.offset = (offset_x, offset_y)


def send_move_command(server: subprocess.Popen, dx: int, dy: int) -> None:
    if server.stdin is None:
        return
    payload = {"type": "move_pawn", "dx": dx, "dy": dy}
    try:
        server.stdin.write(json.dumps(payload) + "\n")
        server.stdin.flush()
    except BrokenPipeError:
        pass


def send_toggle_sleep(server: subprocess.Popen) -> None:
    if server.stdin is None:
        return
    payload = {"type": "toggle_sleep"}
    try:
        server.stdin.write(json.dumps(payload) + "\n")
        server.stdin.flush()
    except BrokenPipeError:
        pass


def handle_events(server: subprocess.Popen) -> bool:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return False
            if event.key in MOVE_KEYS:
                dx, dy = MOVE_KEYS[event.key]
                send_move_command(server, dx, dy)
            if event.key == pygame.K_SPACE:
                send_toggle_sleep(server)
    return True


def draw_snapshot(screen: pygame.Surface, snapshot: Dict, state: ViewerState) -> None:
    screen.fill(COLORS["bg"])
    interior = snapshot.get("interior")
    if not interior:
        draw_message(screen, "Awaiting interior data...")
        pygame.display.flip()
        return

    ensure_layout(snapshot, state)
    if state.tile_size is None:
        draw_message(screen, "Interior not initialized")
        pygame.display.flip()
        return

    tile_size = state.tile_size
    offset_x, offset_y = state.offset
    tiles = interior.get("tiles", [])
    for y, row in enumerate(tiles):
        for x, tile_name in enumerate(row):
            rect = pygame.Rect(
                offset_x + x * tile_size,
                offset_y + y * tile_size,
                tile_size,
                tile_size,
            )
            draw_tile(screen, rect, tile_name)

    draw_devices(screen, interior.get("devices", []), tile_size, offset_x, offset_y)
    draw_pawn(screen, interior.get("pawn"), tile_size, offset_x, offset_y)
    draw_hud(screen, interior)
    pygame.display.flip()


def draw_tile(screen: pygame.Surface, rect: pygame.Rect, tile_name: str) -> None:
    name = tile_name or "Empty"
    if name == "Wall":
        pygame.draw.rect(screen, COLORS["wall"], rect)
    elif name == "Bed":
        pygame.draw.rect(screen, COLORS["bed"], rect)
        inner = rect.inflate(-rect.width * 0.4, -rect.height * 0.4)
        pygame.draw.rect(screen, COLORS["fg"], inner, width=1)
    elif name == "DoorClosed":
        pygame.draw.rect(screen, COLORS["door"], rect)
    elif name == "DoorOpen":
        pygame.draw.rect(screen, COLORS["door_open"], rect)
        pygame.draw.rect(screen, COLORS["fg_dim"], rect, width=1)
    elif name == "Floor":
        pygame.draw.rect(screen, COLORS["floor"], rect)
    else:
        pygame.draw.rect(screen, COLORS["grid"], rect)
    pygame.draw.rect(screen, COLORS["grid"], rect, width=1)


def draw_devices(
    screen: pygame.Surface,
    devices: List[Dict],
    tile_size: int,
    offset_x: int,
    offset_y: int,
) -> None:
    for device in devices:
        x = device.get("x", 0)
        y = device.get("y", 0)
        w = device.get("w", 1)
        h = device.get("h", 1)
        rect = pygame.Rect(
            offset_x + x * tile_size,
            offset_y + y * tile_size,
            tile_size * w,
            tile_size * h,
        )
        color = COLORS["device"]
        kind = device.get("kind", "")
        if kind == "ReactorUranium":
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, COLORS["bg"], rect.inflate(-tile_size * 0.5, -tile_size * 0.5))
        elif kind == "Tank":
            pygame.draw.rect(screen, color, rect)
        elif kind == "Dispenser":
            pygame.draw.rect(screen, COLORS["device_dim"], rect)
            nozzle = rect.inflate(-rect.width * 0.4, -rect.height * 0.4)
            pygame.draw.rect(screen, COLORS["fg"], nozzle, width=1)
        elif kind == "Light":
            pygame.draw.circle(
                screen,
                COLORS["fg"],
                (rect.centerx, rect.centery),
                max(2, tile_size // 6),
            )
        else:
            pygame.draw.rect(screen, COLORS["device_dim"], rect)
        pygame.draw.rect(screen, COLORS["grid"], rect, width=1)


def draw_pawn(
    screen: pygame.Surface,
    pawn: Optional[Dict],
    tile_size: int,
    offset_x: int,
    offset_y: int,
) -> None:
    if not pawn:
        return
    x = pawn.get("x", 0)
    y = pawn.get("y", 0)
    rect = pygame.Rect(
        offset_x + x * tile_size,
        offset_y + y * tile_size,
        tile_size,
        tile_size,
    )
    inner = rect.inflate(-tile_size * 0.4, -tile_size * 0.4)
    pygame.draw.rect(screen, COLORS["pawn"], inner)


def draw_hud(screen: pygame.Surface, interior: Dict) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    pawn = interior.get("pawn", {})
    needs = pawn.get("needs", {})
    power = interior.get("power", {})
    lines = [
        f"Status: {pawn.get('status', 'Unknown')}",
        f"Hunger: {needs.get('hunger', 0.0) * 100:.0f}%",
        f"Thirst: {needs.get('thirst', 0.0) * 100:.0f}%",
        f"Rest: {needs.get('rest', 0.0) * 100:.0f}%",
        f"Net power: {power.get('net_kw', 0.0):.1f} kW",
    ]
    padding = 10
    line_height = FONT_SMALL.get_linesize()
    width = max(FONT_SMALL.size(line)[0] for line in lines) + padding * 2
    height = line_height * len(lines) + padding * 2
    rect = pygame.Rect(TILE_MARGIN, TILE_MARGIN, width, height)
    pygame.draw.rect(screen, COLORS["hud_bg"], rect)
    pygame.draw.rect(screen, COLORS["hud_border"], rect, width=1)
    y = rect.top + padding
    for line in lines:
        surface = FONT_SMALL.render(line, True, COLORS["fg"])
        screen.blit(surface, (rect.left + padding, y))
        y += line_height


def draw_message(screen: pygame.Surface, message: str) -> None:
    if FONT_MEDIUM is None:
        return
    surface = FONT_MEDIUM.render(message, True, COLORS["fg"])
    rect = surface.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
    screen.blit(surface, rect)


def main() -> None:
    server = launch_server()
    screen = init_pygame()
    state = ViewerState()
    snapshot: Optional[Dict] = None

    try:
        while True:
            if not handle_events(server):
                break

            line = server.stdout.readline() if server.stdout else ""
            if line == "":
                break
            line = line.strip()
            if not line:
                continue

            snapshot = json.loads(line)
            draw_snapshot(screen, snapshot, state)
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

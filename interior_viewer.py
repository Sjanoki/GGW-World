#!/usr/bin/env python3
"""Interior viewer for GGW – shows pawn stats and device context."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 900
MARGIN = 120
FONT_NAME = "consolas"
FONT_SMALL_SIZE = 18
FONT_MEDIUM_SIZE = 22
ZOOM_STEP = 1.1
ZOOM_MIN = 0.5
ZOOM_MAX = 4.0
BAR_WIDTH = 140
BAR_HEIGHT = 10
PANEL_PADDING = 12

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
    "highlight": (182, 255, 201),
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
        self.base_tile_size: Optional[float] = None
        self.tile_size: int = 32
        self.offset: Tuple[int, int] = (0, 0)
        self.zoom: float = 1.0
        self.selected_device_id: Optional[int] = None


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


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def ensure_layout(interior: Dict, state: ViewerState) -> None:
    width = max(1, interior.get("width", 1))
    height = max(1, interior.get("height", 1))
    if state.base_tile_size is None:
        usable_w = max(1.0, WINDOW_WIDTH - MARGIN * 2)
        usable_h = max(1.0, WINDOW_HEIGHT - MARGIN * 2)
        tile_w = usable_w / width
        tile_h = usable_h / height
        state.base_tile_size = max(8.0, min(tile_w, tile_h))
    tile_size = max(8, int(state.base_tile_size * state.zoom))
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


def send_interact(server: subprocess.Popen, snapshot: Optional[Dict]) -> None:
    if server.stdin is None or not snapshot:
        return
    interior = snapshot.get("interior") or {}
    pawn = interior.get("pawn") or {}
    x = pawn.get("x")
    y = pawn.get("y")
    if x is None or y is None:
        return
    payload = {"type": "interact_at", "x": int(x), "y": int(y)}
    try:
        server.stdin.write(json.dumps(payload) + "\n")
        server.stdin.flush()
    except BrokenPipeError:
        pass


def screen_to_tile(state: ViewerState, pos: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    tile_size = state.tile_size
    if tile_size <= 0:
        return None
    x = (pos[0] - state.offset[0]) // tile_size
    y = (pos[1] - state.offset[1]) // tile_size
    if x < 0 or y < 0:
        return None
    return int(x), int(y)


def handle_right_click(
    state: ViewerState, snapshot: Optional[Dict], pos: Tuple[int, int]
) -> None:
    if not snapshot:
        return
    interior = snapshot.get("interior") or {}
    tile = screen_to_tile(state, pos)
    if tile is None:
        return
    width = interior.get("width", 0)
    height = interior.get("height", 0)
    tx, ty = tile
    if tx >= width or ty >= height:
        state.selected_device_id = None
        return
    device = find_device_at(interior, tx, ty)
    state.selected_device_id = device.get("id") if device else None


def handle_events(
    server: subprocess.Popen, state: ViewerState, snapshot: Optional[Dict]
) -> bool:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if state.selected_device_id is not None:
                    state.selected_device_id = None
                else:
                    return False
            if event.key in MOVE_KEYS:
                dx, dy = MOVE_KEYS[event.key]
                send_move_command(server, dx, dy)
            if event.key == pygame.K_SPACE:
                send_toggle_sleep(server)
            if event.key == pygame.K_e:
                send_interact(server, snapshot)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 3:
                handle_right_click(state, snapshot, event.pos)
            elif event.button == 4:
                state.zoom = clamp(state.zoom * ZOOM_STEP, ZOOM_MIN, ZOOM_MAX)
            elif event.button == 5:
                state.zoom = clamp(state.zoom / ZOOM_STEP, ZOOM_MIN, ZOOM_MAX)
    return True


def draw_snapshot(screen: pygame.Surface, snapshot: Dict, state: ViewerState) -> None:
    screen.fill(COLORS["bg"])
    interior = snapshot.get("interior")
    if not interior:
        draw_message(screen, "Awaiting interior data...")
        pygame.display.flip()
        return

    ensure_layout(interior, state)
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

    draw_devices(screen, interior.get("devices", []), state)
    draw_pawn(screen, interior.get("pawn"), tile_size, offset_x, offset_y)
    draw_context_panel(screen, interior, state)
    draw_pawn_panel(screen, interior)
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
        pygame.draw.rect(screen, COLORS["bg"], rect)
    pygame.draw.rect(screen, COLORS["grid"], rect, width=1)


def draw_devices(screen: pygame.Surface, devices: List[Dict], state: ViewerState) -> None:
    tile_size = state.tile_size
    offset_x, offset_y = state.offset
    labels = tile_size >= 24
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
        kind = device.get("kind", "")
        color = COLORS["device"] if device.get("online", True) else COLORS["device_dim"]
        pygame.draw.rect(screen, color, rect)
        pygame.draw.rect(screen, COLORS["grid"], rect, width=1)
        if state.selected_device_id == device.get("id"):
            pygame.draw.rect(screen, COLORS["highlight"], rect, width=2)
        if labels and FONT_SMALL is not None:
            code = device_label(kind)
            if code:
                text = FONT_SMALL.render(code, True, COLORS["bg"])
                text_rect = text.get_rect(center=rect.center)
                screen.blit(text, text_rect)


def device_label(kind: str) -> str:
    labels = {
        "ReactorUranium": "RX",
        "Tank": "TK",
        "Dispenser": "DS",
        "Light": "LT",
        "DoorDevice": "DR",
        "BedDevice": "BD",
        "Transponder": "TR",
        "ShipComputer": "SC",
        "FoodGenerator": "FG",
    }
    return labels.get(kind, "")


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


def draw_context_panel(screen: pygame.Surface, interior: Dict, state: ViewerState) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    device = find_selected_device(interior, state.selected_device_id)
    if not device:
        return
    lines = build_device_lines(device)
    title = device.get("kind", "Device")
    draw_panel(
        screen,
        title,
        lines,
        pygame.Rect(WINDOW_WIDTH - 320, PANEL_PADDING, 300, 0),
    )


def draw_pawn_panel(screen: pygame.Surface, interior: Dict) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    pawn = interior.get("pawn", {})
    needs = pawn.get("needs", {})
    lines = [
        f"Status: {pawn.get('status', 'Unknown')}",
        f"Hunger: {needs.get('hunger', 0.0) * 100:.0f}%",
        f"Thirst: {needs.get('thirst', 0.0) * 100:.0f}%",
        f"Rest: {needs.get('rest', 0.0) * 100:.0f}%",
        f"Net power: {interior.get('power', {}).get('net_kw', 0.0):.1f} kW",
    ]
    rect = pygame.Rect(PANEL_PADDING, WINDOW_HEIGHT - 260, 320, 0)
    draw_panel(screen, "Pawn", lines, rect)

    health = (pawn.get("health") or {}).get("body_parts", [])
    if not health or FONT_SMALL is None:
        return
    x = rect.left + PANEL_PADDING
    y = rect.bottom - PANEL_PADDING + 10
    for part in health:
        name = part.get("name", "?")
        hp = float(part.get("hp", 0.0))
        max_hp = max(1.0, float(part.get("max_hp", 1.0)))
        frac = clamp(hp / max_hp, 0.0, 1.0)
        label = FONT_SMALL.render(name, True, COLORS["fg"])
        screen.blit(label, (x, y))
        bar_rect = pygame.Rect(x, y + FONT_SMALL.get_linesize() - 4, BAR_WIDTH, BAR_HEIGHT)
        pygame.draw.rect(screen, COLORS["fg_dim"], bar_rect, width=1)
        fill_rect = bar_rect.inflate(-2, -2)
        fill_rect.width = int((BAR_WIDTH - 4) * frac)
        pygame.draw.rect(screen, COLORS["fg"], fill_rect)
        y += BAR_HEIGHT + FONT_SMALL.get_linesize()


def draw_panel(
    screen: pygame.Surface,
    title: str,
    lines: List[str],
    rect: pygame.Rect,
) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    width = max(
        [FONT_MEDIUM.size(title)[0]] + [FONT_SMALL.size(line)[0] for line in lines]
    )
    height = FONT_MEDIUM.get_linesize() + len(lines) * FONT_SMALL.get_linesize()
    panel_rect = pygame.Rect(rect.left, rect.top, width + PANEL_PADDING * 2, height + PANEL_PADDING * 2)
    pygame.draw.rect(screen, COLORS["hud_bg"], panel_rect)
    pygame.draw.rect(screen, COLORS["hud_border"], panel_rect, width=1)
    y = panel_rect.top + PANEL_PADDING
    screen.blit(FONT_MEDIUM.render(title, True, COLORS["fg"]), (panel_rect.left + PANEL_PADDING, y))
    y += FONT_MEDIUM.get_linesize()
    for line in lines:
        screen.blit(FONT_SMALL.render(line, True, COLORS["fg"]), (panel_rect.left + PANEL_PADDING, y))
        y += FONT_SMALL.get_linesize()


def find_device_at(interior: Dict, tx: int, ty: int) -> Optional[Dict]:
    for device in interior.get("devices", []):
        x = device.get("x", 0)
        y = device.get("y", 0)
        w = device.get("w", 1)
        h = device.get("h", 1)
        if x <= tx < x + w and y <= ty < y + h:
            return device
    return None


def find_selected_device(interior: Dict, device_id: Optional[int]) -> Optional[Dict]:
    if device_id is None:
        return None
    for device in interior.get("devices", []):
        if device.get("id") == device_id:
            return device
    return None


def build_device_lines(device: Dict) -> List[str]:
    lines = [
        f"Pos: ({device.get('x', 0)}, {device.get('y', 0)})",
        f"Size: {device.get('w', 1)}x{device.get('h', 1)}",
        f"Online: {device.get('online', True)}",
        f"Power: {device.get('power_kw', 0.0):.1f} kW",
    ]
    kind = device.get("kind")
    if kind == "ReactorUranium":
        lines.append(f"Fuel: {device.get('fuel_kg', 0.0):.1f} / {device.get('max_fuel_kg', 0.0):.1f} kg")
        lines.append(f"Output: {device.get('power_output_kw', 0.0):.0f} kW")
    elif kind == "Tank":
        lines.append(f"O2: {device.get('o2_kg', 0.0):.1f} kg")
        lines.append(f"N2: {device.get('n2_kg', 0.0):.1f} kg")
        lines.append(f"CO2: {device.get('co2_kg', 0.0):.1f} kg")
    elif kind == "Dispenser":
        lines.append(f"Gas: {device.get('gas_type', 'Unknown')}")
        lines.append(f"Rate: {device.get('rate_kg_per_s', 0.0):.3f} kg/s")
        lines.append(f"Active: {device.get('active', False)}")
    elif kind == "Light":
        lines.append(f"Intensity: {device.get('intensity', 0.0):.1f}")
    elif kind == "DoorDevice":
        lines.append(f"Open: {device.get('open', False)}")
    elif kind == "FoodGenerator":
        lines.append(f"Food: {device.get('food_units', 0.0):.1f} units")
    elif kind == "Transponder":
        lines.append(f"Callsign: {device.get('callsign', 'N/A')}")
    elif kind == "ShipComputer":
        lines.append(f"Online: {device.get('ship_computer_online', False)}")
    return lines


def draw_message(screen: pygame.Surface, message: str) -> None:
    if FONT_MEDIUM is None:
        return
    surface = FONT_MEDIUM.render(message, True, COLORS["fg"])
    rect = surface.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
    screen.blit(surface, rect)


def prune_selection(state: ViewerState, interior: Dict) -> None:
    if state.selected_device_id is None:
        return
    if not find_selected_device(interior, state.selected_device_id):
        state.selected_device_id = None


def main() -> None:
    server = launch_server()
    screen = init_pygame()
    state = ViewerState()
    snapshot: Optional[Dict] = None

    try:
        while True:
            if not handle_events(server, state, snapshot):
                break

            line = server.stdout.readline() if server.stdout else ""
            if line == "":
                break
            line = line.strip()
            if not line:
                continue

            snapshot = json.loads(line)
            interior = snapshot.get("interior")
            if interior:
                prune_selection(state, interior)
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

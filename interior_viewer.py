#!/usr/bin/env python3
"""Interior viewer for GGW – shows pawn stats and device context."""

from __future__ import annotations

import json
import math
import socket
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 40000

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
    "planet_fill": (6, 20, 10),
    "planet_outline": (0, 180, 90),
}

INTERACTIVE_MODAL_KINDS = {
    "ReactorUranium",
    "NavStation",
    "Transponder",
    "ShipComputer",
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

COMMS_LOG_LIMIT = 14
COMMS_MENU_OPTIONS = [
    "Request undocking clearance",
    "SOS: Out of fuel",
    "Request crew list",
    "Show on nav map",
]
DEFAULT_COMMS_LOG = [
    "[15:30] LINK: Connected to GGW-PORT",
    "[15:31] CTRL: Cleared for departure. Have a safe flight.",
]

SHIP_POWER_GROUP_ORDER = ["Reactor", "Life Support", "Nav & Comms", "Misc"]

FONT_SMALL: Optional[pygame.font.Font] = None
FONT_MEDIUM: Optional[pygame.font.Font] = None


class ViewerState:
    def __init__(self) -> None:
        self.base_tile_size: Optional[float] = None
        self.tile_size: int = 32
        self.offset: Tuple[int, int] = (0, 0)
        self.zoom: float = 1.0
        self.selected_device_id: Optional[int] = None
        self.modal_device_id: Optional[int] = None
        self.context_tile: Optional[Tuple[int, int]] = None
        self.navstation_tab: str = "NAV"
        self.nav_tab_rects: Dict[str, pygame.Rect] = {}
        self.nav_comms_log: List[str] = list(DEFAULT_COMMS_LOG)
        self.nav_comms_selected: int = 0
        self.shipcomp_selection: int = 0


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
    state.tile_size = tile_size


def update_camera_follow(interior: Dict, state: ViewerState) -> None:
    tile_size = state.tile_size
    pawn = interior.get("pawn") or {}
    width = interior.get("width", 1)
    height = interior.get("height", 1)
    px = pawn.get("x")
    py = pawn.get("y")
    if px is None or py is None:
        px = max(0.0, width / 2.0 - 0.5)
        py = max(0.0, height / 2.0 - 0.5)
    center_x = (float(px) + 0.5) * tile_size
    center_y = (float(py) + 0.5) * tile_size
    offset_x = int(WINDOW_WIDTH / 2 - center_x)
    offset_y = int(WINDOW_HEIGHT / 2 - center_y)
    state.offset = (offset_x, offset_y)


def send_move_command(conn: ServerConnection, dx: int, dy: int) -> None:
    payload = {"type": "move_pawn", "dx": dx, "dy": dy}
    conn.send_json(payload)


def send_toggle_sleep(conn: ServerConnection) -> None:
    payload = {"type": "toggle_sleep"}
    conn.send_json(payload)


def send_interact_at(conn: ServerConnection, x: int, y: int) -> None:
    payload = {"type": "interact_at", "x": int(x), "y": int(y)}
    conn.send_json(payload)


def send_interact_device(conn: ServerConnection, device: Dict) -> None:
    x = int(device.get("x", 0))
    y = int(device.get("y", 0))
    send_interact_at(conn, x, y)


def send_device_action(conn: ServerConnection, device_id: int, action: str) -> None:
    payload = {"type": "device_action", "device_id": int(device_id), "action": action}
    conn.send_json(payload)


def send_ship_computer_toggle(conn: ServerConnection, device_id: int) -> None:
    payload = {"type": "ship_computer_toggle", "device_id": int(device_id)}
    conn.send_json(payload)


def screen_to_tile(state: ViewerState, pos: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    tile_size = state.tile_size
    if tile_size <= 0:
        return None
    x = (pos[0] - state.offset[0]) // tile_size
    y = (pos[1] - state.offset[1]) // tile_size
    if x < 0 or y < 0:
        return None
    return int(x), int(y)


def parse_tile_entry(entry: Any) -> Tuple[str, Optional[Dict[str, Any]]]:
    if isinstance(entry, dict):
        tile_type = entry.get("type") or entry.get("tile_type") or "Empty"
        return str(tile_type), entry.get("atmos")
    if entry is None:
        return "Empty", None
    return str(entry), None


def tile_info_at(interior: Dict, tx: int, ty: int) -> Optional[Dict[str, Any]]:
    tiles = interior.get("tiles", [])
    if ty < 0 or ty >= len(tiles):
        return None
    row = tiles[ty]
    if tx < 0 or tx >= len(row):
        return None
    tile_type, atmos = parse_tile_entry(row[tx])
    return {"type": tile_type, "atmos": atmos}


def build_atmo_lines(atmos: Optional[Dict[str, Any]]) -> List[str]:
    if not atmos:
        return []
    pressure = float(atmos.get("pressure_kpa", 0.0))
    o2 = float(atmos.get("o2_kg", 0.0))
    n2 = float(atmos.get("n2_kg", 0.0))
    co2 = float(atmos.get("co2_kg", 0.0))
    return [
        "Atmos:",
        f"  P: {pressure:.1f} kPa",
        f"  O2: {o2:.2f} kg",
        f"  N2: {n2:.2f} kg",
        f"  CO2: {co2:.3f} kg",
    ]


def build_tile_context_lines(
    tile_info: Dict[str, Any], pos: Tuple[int, int]
) -> Tuple[List[str], str]:
    tile_type = tile_info.get("type", "Empty")
    lines = [f"Pos: ({pos[0]}, {pos[1]})"]
    if tile_type == "Wall":
        lines.append("Standard wall. No atmosphere sample.")
        return lines, "Standard Wall"
    atmo_lines = build_atmo_lines(tile_info.get("atmos"))
    if atmo_lines:
        lines.extend(atmo_lines)
    else:
        lines.append("Atmos: n/a")
    return lines, tile_type


def handle_right_click(
    state: ViewerState, snapshot: Optional[Dict], pos: Tuple[int, int]
) -> None:
    if not snapshot:
        return
    interior = snapshot.get("interior") or {}
    tile = screen_to_tile(state, pos)
    if tile is None:
        state.context_tile = None
        state.selected_device_id = None
        return
    width = interior.get("width", 0)
    height = interior.get("height", 0)
    tx, ty = tile
    if tx >= width or ty >= height:
        state.context_tile = None
        state.selected_device_id = None
        return
    state.context_tile = (tx, ty)
    device = find_device_at(interior, tx, ty)
    state.selected_device_id = device.get("id") if device else None


def handle_events(
    conn: ServerConnection, state: ViewerState, snapshot: Optional[Dict]
) -> bool:
    modal_open = state.modal_device_id is not None
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if state.modal_device_id is not None:
                    state.modal_device_id = None
                    state.nav_tab_rects.clear()
                elif state.selected_device_id is not None or state.context_tile is not None:
                    state.selected_device_id = None
                    state.context_tile = None
                else:
                    return False
                modal_open = state.modal_device_id is not None
            elif event.key == pygame.K_e and not modal_open:
                handle_interact_press(conn, state, snapshot)
                modal_open = state.modal_device_id is not None
            elif modal_open and handle_modal_key(conn, state, snapshot, event.key):
                continue
            elif not modal_open and event.key in MOVE_KEYS:
                dx, dy = MOVE_KEYS[event.key]
                send_move_command(conn, dx, dy)
            elif not modal_open and event.key == pygame.K_SPACE:
                send_toggle_sleep(conn)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 3:
                if state.modal_device_id is None:
                    handle_right_click(state, snapshot, event.pos)
            elif event.button == 1 and state.modal_device_id is not None:
                if handle_nav_modal_click(state, snapshot, event.pos):
                    continue
            elif event.button == 4:
                state.zoom = clamp(state.zoom * ZOOM_STEP, ZOOM_MIN, ZOOM_MAX)
            elif event.button == 5:
                state.zoom = clamp(state.zoom / ZOOM_STEP, ZOOM_MIN, ZOOM_MAX)
    return True


def handle_interact_press(
    conn: ServerConnection, state: ViewerState, snapshot: Optional[Dict]
) -> None:
    if not snapshot:
        return
    interior = snapshot.get("interior") or {}
    device = find_device_near_pawn(interior)
    if not device:
        return
    send_interact_device(conn, device)
    if device_allows_modal(device):
        state.modal_device_id = device.get("id")
        kind = device.get("kind")
        if kind == "NavStation":
            state.navstation_tab = "NAV"
        if kind == "ShipComputer":
            state.shipcomp_selection = 0
    else:
        state.modal_device_id = None


def handle_nav_modal_click(state: ViewerState, snapshot: Optional[Dict], pos: Tuple[int, int]) -> bool:
    if snapshot is None:
        return False
    if state.modal_device_id is None:
        return False
    interior = snapshot.get("interior") or {}
    device = find_selected_device(interior, state.modal_device_id)
    if not device or device.get("kind") != "NavStation":
        return False
    for label, rect in state.nav_tab_rects.items():
        if rect.collidepoint(pos):
            state.navstation_tab = label
            if label == "COMMS":
                state.nav_comms_selected = 0
            return True
    return False


def handle_nav_modal_keypress(state: ViewerState, key: int) -> bool:
    if state.navstation_tab != "COMMS":
        return False
    if not COMMS_MENU_OPTIONS:
        return False
    if key in (pygame.K_UP, pygame.K_w):
        state.nav_comms_selected = (state.nav_comms_selected - 1) % len(COMMS_MENU_OPTIONS)
        return True
    if key in (pygame.K_DOWN, pygame.K_s):
        state.nav_comms_selected = (state.nav_comms_selected + 1) % len(COMMS_MENU_OPTIONS)
        return True
    if key in (pygame.K_RETURN, pygame.K_SPACE):
        option = COMMS_MENU_OPTIONS[state.nav_comms_selected]
        timestamp = time.strftime("%H:%M")
        append_comms_log(state, f"[{timestamp}] SHIP: {option}")
        print(f"COMMS >> {option}", flush=True)
        return True
    return False


def append_comms_log(state: ViewerState, line: str) -> None:
    state.nav_comms_log.append(line)
    if len(state.nav_comms_log) > COMMS_LOG_LIMIT:
        state.nav_comms_log = state.nav_comms_log[-COMMS_LOG_LIMIT:]


def ship_computer_ordered_devices(summary: Dict) -> List[Dict]:
    devices = summary.get("devices") or []
    grouped: Dict[str, List[Dict]] = {}
    for entry in devices:
        group = entry.get("group", "Misc")
        grouped.setdefault(group, []).append(entry)
    ordered: List[Dict] = []
    for group in SHIP_POWER_GROUP_ORDER:
        for entry in sorted(grouped.get(group, []), key=lambda item: item.get("name", "")):
            ordered.append(entry)
    # Include any unexpected groups at the end
    for group, entries in grouped.items():
        if group in SHIP_POWER_GROUP_ORDER:
            continue
        for entry in sorted(entries, key=lambda item: item.get("name", "")):
            ordered.append(entry)
    return ordered


def handle_ship_computer_modal_key(
    conn: ServerConnection, state: ViewerState, snapshot: Optional[Dict], key: int
) -> bool:
    if snapshot is None:
        return False
    interior = snapshot.get("interior") or {}
    summary = interior.get("power_summary") or {}
    ordered = ship_computer_ordered_devices(summary)
    if not ordered:
        return False
    state.shipcomp_selection = max(0, min(state.shipcomp_selection, len(ordered) - 1))
    if key in (pygame.K_UP, pygame.K_w):
        state.shipcomp_selection = (state.shipcomp_selection - 1) % len(ordered)
        return True
    if key in (pygame.K_DOWN, pygame.K_s):
        state.shipcomp_selection = (state.shipcomp_selection + 1) % len(ordered)
        return True
    if key in (pygame.K_RETURN, pygame.K_SPACE):
        selected = ordered[state.shipcomp_selection]
        if selected.get("controllable"):
            send_ship_computer_toggle(conn, int(selected.get("id", 0)))
        return True
    return False


def draw_snapshot(screen: pygame.Surface, snapshot: Dict, state: ViewerState) -> None:
    screen.fill(COLORS["bg"])
    interior = snapshot.get("interior")
    if not interior:
        draw_message(screen, "Awaiting interior data...")
        pygame.display.flip()
        return

    ensure_layout(interior, state)
    update_camera_follow(interior, state)
    tile_size = state.tile_size
    offset_x, offset_y = state.offset

    tiles = interior.get("tiles", [])
    for y, row in enumerate(tiles):
        for x, entry in enumerate(row):
            tile_name, _ = parse_tile_entry(entry)
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
    draw_device_modal(screen, snapshot, state)
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
        if state.modal_device_id == device.get("id"):
            pygame.draw.rect(screen, COLORS["fg"], rect, width=2)
        if labels and FONT_SMALL is not None:
            code = device_label(kind)
            if code:
                text = FONT_SMALL.render(code, True, COLORS["bg"])
                text_rect = text.get_rect(center=rect.center)
                screen.blit(text, text_rect)
        if kind == "DoorDevice":
            open_state = device.get("open", False)
            if open_state:
                pygame.draw.line(
                    screen,
                    COLORS["highlight"],
                    (rect.left + 4, rect.centery),
                    (rect.right - 4, rect.centery),
                    2,
                )
            else:
                pygame.draw.line(
                    screen,
                    COLORS["highlight"],
                    (rect.centerx, rect.top + 4),
                    (rect.centerx, rect.bottom - 4),
                    2,
                )


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
        "NavStation": "NV",
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
    cx = int(offset_x + (x + 0.5) * tile_size)
    cy = int(offset_y + (y + 0.5) * tile_size)
    body_radius = max(2, int(tile_size * 0.35))
    head_radius = max(1, int(tile_size * 0.22))
    arm_radius = max(1, int(tile_size * 0.18))
    head_center = (cx, int(cy - tile_size * 0.25))
    left_arm_center = (int(cx - tile_size * 0.25), cy)
    right_arm_center = (int(cx + tile_size * 0.25), cy)
    pygame.draw.circle(screen, COLORS["pawn"], (cx, cy), body_radius)
    pygame.draw.circle(screen, COLORS["pawn"], head_center, head_radius)
    pygame.draw.circle(screen, COLORS["pawn"], left_arm_center, arm_radius)
    pygame.draw.circle(screen, COLORS["pawn"], right_arm_center, arm_radius)


def draw_context_panel(screen: pygame.Surface, interior: Dict, state: ViewerState) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    if state.context_tile is None:
        return
    tx, ty = state.context_tile
    tile_info = tile_info_at(interior, tx, ty)
    if tile_info is None:
        state.context_tile = None
        state.selected_device_id = None
        return
    device = find_device_at(interior, tx, ty)
    if device:
        lines = build_device_lines(device)
        atmo_lines = build_atmo_lines(tile_info.get("atmos"))
        if atmo_lines:
            lines += [""] + atmo_lines
        title = device.get("kind", "Device")
    else:
        lines, title = build_tile_context_lines(tile_info, (tx, ty))
    draw_panel(
        screen,
        title,
        lines,
        pygame.Rect(WINDOW_WIDTH - 320, PANEL_PADDING, 300, 0),
    )


def draw_device_modal(screen: pygame.Surface, snapshot: Dict, state: ViewerState) -> None:
    if state.modal_device_id is None or FONT_SMALL is None or FONT_MEDIUM is None:
        return
    interior = snapshot.get("interior") or {}
    device = find_selected_device(interior, state.modal_device_id)
    if not device:
        state.modal_device_id = None
        state.nav_tab_rects.clear()
        return
    state.nav_tab_rects = {}
    if device.get("kind") == "NavStation":
        draw_navstation_modal(screen, snapshot, state, device)
        return
    if device.get("kind") == "ShipComputer":
        draw_ship_computer_modal(screen, snapshot, state)
        return
    title, lines, action_lines = build_modal_content(device, snapshot)
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 120))
    screen.blit(overlay, (0, 0))
    content_lines = lines + ([""] if lines and action_lines else []) + action_lines
    width = max(
        [FONT_MEDIUM.size(title)[0]]
        + [FONT_SMALL.size(line)[0] for line in content_lines]
    )
    height = (
        FONT_MEDIUM.get_linesize()
        + len(content_lines) * FONT_SMALL.get_linesize()
        + PANEL_PADDING * 2
    )
    panel_rect = pygame.Rect(
        (WINDOW_WIDTH - (width + PANEL_PADDING * 2)) // 2,
        (WINDOW_HEIGHT - height) // 2,
        width + PANEL_PADDING * 2,
        height,
    )
    pygame.draw.rect(screen, COLORS["hud_bg"], panel_rect)
    pygame.draw.rect(screen, COLORS["hud_border"], panel_rect, width=2)
    y = panel_rect.top + PANEL_PADDING
    screen.blit(
        FONT_MEDIUM.render(title, True, COLORS["fg"]),
        (panel_rect.left + PANEL_PADDING, y),
    )
    y += FONT_MEDIUM.get_linesize()
    for line in content_lines:
        screen.blit(
            FONT_SMALL.render(line, True, COLORS["fg"]),
            (panel_rect.left + PANEL_PADDING, y),
        )
        y += FONT_SMALL.get_linesize()


def draw_navstation_modal(
    screen: pygame.Surface, snapshot: Dict, state: ViewerState, device: Dict
) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    interior = snapshot.get("interior") or {}
    nav_context = interior.get("nav_context") or {}
    if state.navstation_tab not in ("NAV", "COMMS"):
        state.navstation_tab = "NAV"
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 120))
    screen.blit(overlay, (0, 0))
    modal_width = int(WINDOW_WIDTH * 0.95)
    modal_height = int(WINDOW_HEIGHT * 0.88)
    panel_rect = pygame.Rect(
        (WINDOW_WIDTH - modal_width) // 2,
        (WINDOW_HEIGHT - modal_height) // 2,
        modal_width,
        modal_height,
    )
    pygame.draw.rect(screen, COLORS["hud_bg"], panel_rect)
    pygame.draw.rect(screen, COLORS["hud_border"], panel_rect, width=2)
    title = FONT_MEDIUM.render("NavStation", True, COLORS["fg"])
    screen.blit(title, (panel_rect.left + PANEL_PADDING, panel_rect.top + PANEL_PADDING))
    tab_top = panel_rect.top + PANEL_PADDING + FONT_MEDIUM.get_linesize() + 8
    nav_rect = pygame.Rect(panel_rect.left + PANEL_PADDING, tab_top, 160, 36)
    comm_rect = pygame.Rect(nav_rect.right + 16, tab_top, 180, 36)
    state.nav_tab_rects = {"NAV": nav_rect, "COMMS": comm_rect}
    for label, rect in state.nav_tab_rects.items():
        active = state.navstation_tab == label
        fill = COLORS["hud_bg"] if not active else (18, 30, 24)
        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, COLORS["hud_border"], rect, width=1)
        text = FONT_SMALL.render(label, True, COLORS["fg"] if active else COLORS["fg_dim"])
        text_rect = text.get_rect(center=rect.center)
        screen.blit(text, text_rect)
    content_top = nav_rect.bottom + 16
    if state.navstation_tab != "COMMS":
        radar_rect = pygame.Rect(
            panel_rect.left + PANEL_PADDING,
            content_top,
            int(panel_rect.width * 0.55),
            panel_rect.bottom - PANEL_PADDING - content_top,
        )
        draw_nav_radar(screen, radar_rect, nav_context, snapshot)
        stats_rect = pygame.Rect(
            radar_rect.right + 20,
            content_top,
            panel_rect.right - PANEL_PADDING - (radar_rect.right + 20),
            panel_rect.bottom - PANEL_PADDING - content_top,
        )
        draw_nav_stats(screen, stats_rect, nav_context)
    else:
        draw_nav_comms(screen, panel_rect, content_top, interior, state)


def draw_nav_radar(
    screen: pygame.Surface, rect: pygame.Rect, nav_context: Dict, snapshot: Dict
) -> None:
    pygame.draw.rect(screen, COLORS["bg"], rect)
    pygame.draw.rect(screen, COLORS["hud_border"], rect, width=1)
    center = rect.center
    max_radius = min(rect.width, rect.height) // 2 - 8
    for ring in range(1, 4):
        radius = int(max_radius * ring / 4)
        pygame.draw.circle(screen, COLORS["grid"], center, radius, 1)
    pygame.draw.line(screen, COLORS["grid"], (center[0], rect.top + 4), (center[0], rect.bottom - 4), 1)
    pygame.draw.line(screen, COLORS["grid"], (rect.left + 4, center[1]), (rect.right - 4, center[1]), 1)
    planet_radius = float(snapshot.get("planet_radius_m", 1.0))
    ship_position = nav_context.get("ship_position") or {}
    ship_velocity = nav_context.get("ship_velocity") or {}
    ship_x = float(ship_position.get("x_m", 0.0))
    ship_y = float(ship_position.get("y_m", 0.0))
    ship_radius = math.hypot(ship_x, ship_y)
    max_range = max(planet_radius + 1.0, ship_radius)
    max_range = max(max_range, planet_radius + float(nav_context.get("apoapsis_m", 0.0)))
    for contact in nav_context.get("contacts", []):
        cx = float(contact.get("x_m", 0.0))
        cy = float(contact.get("y_m", 0.0))
        max_range = max(max_range, math.hypot(cx, cy))
    scale = max_radius / max(max_range, 1.0)
    planet_px = max(4, int(planet_radius * scale))
    pygame.draw.circle(screen, COLORS["planet_fill"], center, min(planet_px, max_radius), 0)
    pygame.draw.circle(screen, COLORS["planet_outline"], center, min(planet_px, max_radius), 2)
    orbit_radius = int(ship_radius * scale)
    if orbit_radius > 6:
        pygame.draw.circle(screen, COLORS["grid"], center, min(orbit_radius, max_radius), 1)
    ship_point = (
        int(center[0] + ship_x * scale),
        int(center[1] - ship_y * scale),
    )
    pygame.draw.circle(screen, COLORS["highlight"], ship_point, 6)
    speed = math.hypot(float(ship_velocity.get("x_mps", 0.0)), float(ship_velocity.get("y_mps", 0.0)))
    if speed > 0.0:
        vx = float(ship_velocity.get("x_mps", 0.0)) / speed
        vy = float(ship_velocity.get("y_mps", 0.0)) / speed
        arrow_end = (
            int(ship_point[0] + vx * 40),
            int(ship_point[1] - vy * 40),
        )
        pygame.draw.line(screen, COLORS["highlight"], ship_point, arrow_end, 2)
    for contact in nav_context.get("contacts", []):
        cx = float(contact.get("x_m", 0.0))
        cy = float(contact.get("y_m", 0.0))
        point = (
            int(center[0] + cx * scale),
            int(center[1] - cy * scale),
        )
        pygame.draw.rect(screen, COLORS["fg_dim"], pygame.Rect(point[0] - 3, point[1] - 3, 6, 6), width=1)


def draw_nav_stats(screen: pygame.Surface, rect: pygame.Rect, nav_context: Dict) -> None:
    if FONT_SMALL is None:
        return
    lines = [
        f"Altitude: {format_distance(float(nav_context.get('altitude_m', 0.0)))}",
        f"Apoapsis: {format_distance(float(nav_context.get('apoapsis_m', 0.0)))}",
        f"Periapsis: {format_distance(float(nav_context.get('periapsis_m', 0.0)))}",
        f"Speed: {float(nav_context.get('speed_mps', 0.0)) / 1000:.2f} km/s",
        f"Period: {float(nav_context.get('orbital_period_s', 0.0)) / 3600:.2f} h",
        f"Heading: {nav_context.get('heading', 'Unknown')}",
        "",
        "Contacts:",
    ]
    ship_position = nav_context.get("ship_position") or {}
    ship_x = float(ship_position.get("x_m", 0.0))
    ship_y = float(ship_position.get("y_m", 0.0))
    contacts = nav_context.get("contacts", [])
    if not contacts:
        lines.append("  None in range")
    else:
        for contact in contacts[:4]:
            dx = float(contact.get("x_m", 0.0)) - ship_x
            dy = float(contact.get("y_m", 0.0)) - ship_y
            dist = math.hypot(dx, dy)
            lines.append(
                f"  {contact.get('body_type', 'Object')} #{int(contact.get('id', 0))}: {format_distance(dist)}"
            )
    y = rect.top
    for line in lines:
        text = FONT_SMALL.render(line, True, COLORS["fg"])
        screen.blit(text, (rect.left, y))
        y += FONT_SMALL.get_linesize()


def draw_nav_comms(
    screen: pygame.Surface,
    panel_rect: pygame.Rect,
    content_top: int,
    interior: Dict,
    state: ViewerState,
) -> None:
    if FONT_SMALL is None:
        return
    area = pygame.Rect(
        panel_rect.left + PANEL_PADDING,
        content_top,
        panel_rect.width - PANEL_PADDING * 2,
        panel_rect.bottom - PANEL_PADDING - content_top,
    )
    log_width = int(area.width * 0.6)
    log_rect = pygame.Rect(area.left, area.top, log_width, area.height)
    control_rect = pygame.Rect(log_rect.right + 16, area.top, area.right - log_rect.right - 16, area.height)
    pygame.draw.rect(screen, COLORS["bg"], log_rect)
    pygame.draw.rect(screen, COLORS["hud_border"], log_rect, width=1)
    pygame.draw.rect(screen, COLORS["bg"], control_rect)
    pygame.draw.rect(screen, COLORS["hud_border"], control_rect, width=1)
    header = FONT_SMALL.render("COMMS LOG", True, COLORS["fg"])
    screen.blit(header, (log_rect.left + PANEL_PADDING, log_rect.top + PANEL_PADDING))
    y = log_rect.top + PANEL_PADDING + FONT_SMALL.get_linesize()
    for line in state.nav_comms_log[-COMMS_LOG_LIMIT:]:
        text = FONT_SMALL.render(line, True, COLORS["fg"])
        screen.blit(text, (log_rect.left + PANEL_PADDING, y))
        y += FONT_SMALL.get_linesize()
    transponder = find_device_by_kind(interior, "Transponder") or {}
    dm_code = transponder.get("dm_code", "----")
    callsign = transponder.get("callsign", "N/A")
    control_y = control_rect.top + PANEL_PADDING
    for line in [f"Callsign: {callsign}", f"DM Code: {dm_code}", "", "COMMS CONTROL:"]:
        text = FONT_SMALL.render(line, True, COLORS["fg"])
        screen.blit(text, (control_rect.left + PANEL_PADDING, control_y))
        control_y += FONT_SMALL.get_linesize()
    for idx, option in enumerate(COMMS_MENU_OPTIONS):
        selected = idx == state.nav_comms_selected
        color = COLORS["fg"] if selected else COLORS["fg_dim"]
        label = f"[{idx + 1}] {option}"
        text = FONT_SMALL.render(label, True, color)
        if selected:
            highlight_rect = pygame.Rect(
                control_rect.left + PANEL_PADDING - 4,
                control_y - 4,
                control_rect.width - PANEL_PADDING * 2 + 8,
                FONT_SMALL.get_linesize() + 8,
            )
            pygame.draw.rect(screen, COLORS["grid"], highlight_rect)
        screen.blit(text, (control_rect.left + PANEL_PADDING, control_y))
        control_y += FONT_SMALL.get_linesize() + 4
    footer = FONT_SMALL.render("[↑/↓] Select  [ENTER] Send  [ESC] Close", True, COLORS["fg_dim"])
    screen.blit(footer, (control_rect.left + PANEL_PADDING, control_rect.bottom - FONT_SMALL.get_linesize() - PANEL_PADDING))


def draw_ship_computer_modal(screen: pygame.Surface, snapshot: Dict, state: ViewerState) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    interior = snapshot.get("interior") or {}
    summary = interior.get("power_summary") or {}
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 120))
    screen.blit(overlay, (0, 0))
    modal_width = int(WINDOW_WIDTH * 0.7)
    modal_height = int(WINDOW_HEIGHT * 0.65)
    panel_rect = pygame.Rect(
        (WINDOW_WIDTH - modal_width) // 2,
        (WINDOW_HEIGHT - modal_height) // 2,
        modal_width,
        modal_height,
    )
    pygame.draw.rect(screen, COLORS["hud_bg"], panel_rect)
    pygame.draw.rect(screen, COLORS["hud_border"], panel_rect, width=2)
    title = FONT_MEDIUM.render("Ship Computer", True, COLORS["fg"])
    screen.blit(title, (panel_rect.left + PANEL_PADDING, panel_rect.top + PANEL_PADDING))
    summary_text = (
        f"GEN {summary.get('generation_kw', 0.0):.1f} kW  "
        f"LOAD {summary.get('load_kw', 0.0):.1f} kW  "
        f"NET {summary.get('net_kw', 0.0):+.1f} kW"
    )
    screen.blit(
        FONT_SMALL.render(summary_text, True, COLORS["fg"]),
        (panel_rect.left + PANEL_PADDING, panel_rect.top + PANEL_PADDING + FONT_MEDIUM.get_linesize()),
    )
    ordered = ship_computer_ordered_devices(summary)
    if ordered:
        state.shipcomp_selection = max(0, min(state.shipcomp_selection, len(ordered) - 1))
    content_y = panel_rect.top + PANEL_PADDING + FONT_MEDIUM.get_linesize() + FONT_SMALL.get_linesize() + 8
    row_height = FONT_SMALL.get_linesize() + 6
    current_group = None
    device_index = 0
    for entry in ordered:
        group = entry.get("group", "Misc")
        if group != current_group:
            current_group = group
            group_text = FONT_SMALL.render(f"[{group}]", True, COLORS["fg"])
            screen.blit(group_text, (panel_rect.left + PANEL_PADDING, content_y))
            content_y += row_height
        highlight = device_index == state.shipcomp_selection
        row_rect = pygame.Rect(
            panel_rect.left + PANEL_PADDING,
            content_y,
            panel_rect.width - PANEL_PADDING * 2,
            row_height,
        )
        if highlight:
            pygame.draw.rect(screen, COLORS["grid"], row_rect)
        name = entry.get("name", "Device")
        draw_kw = float(entry.get("draw_kw", 0.0))
        status = "ONLINE" if entry.get("online", False) else "OFFLINE"
        controllable = entry.get("controllable", False)
        color = COLORS["fg"] if entry.get("online", False) else COLORS["fg_dim"]
        text = FONT_SMALL.render(f"* {name:<18} ({draw_kw:>5.1f} kW)  {status}", True, color)
        screen.blit(text, (row_rect.left + 6, row_rect.top + 2))
        if controllable:
            toggle_hint = FONT_SMALL.render("TOGGLE", True, COLORS["fg_dim"])
            screen.blit(toggle_hint, (row_rect.right - toggle_hint.get_width() - 6, row_rect.top + 2))
        content_y += row_height
        device_index += 1
    if not ordered:
        empty = FONT_SMALL.render("No devices linked.", True, COLORS["fg_dim"])
        screen.blit(empty, (panel_rect.left + PANEL_PADDING, content_y))
    instructions = FONT_SMALL.render("[↑/↓] Select  [ENTER] Toggle  [ESC] Close", True, COLORS["fg_dim"])
    screen.blit(
        instructions,
        (panel_rect.left + PANEL_PADDING, panel_rect.bottom - PANEL_PADDING - FONT_SMALL.get_linesize()),
    )
def build_modal_content(device: Dict, snapshot: Dict) -> Tuple[str, List[str], List[str]]:
    title = device.get("kind", "Device")
    lines = build_device_lines(device)
    kind = device.get("kind", "")
    if kind == "ReactorUranium":
        status = "Online" if device.get("reactor_online") else "Offline"
        lines.append(f"Core state: {status}")
    elif kind == "NavStation":
        lines.append("Nav telemetry available in console view.")
    elif kind == "ShipComputer":
        total = len(snapshot.get("interior", {}).get("devices", []))
        lines.append(f"Devices linked: {total}")
    elif kind == "Transponder":
        callsign = device.get("callsign", "N/A")
        lines.append(f"Broadcast ID: {callsign}")
        lines.append(f"DM Code: {device.get('dm_code', '----')}")

    action_lines = [label for _, label, _ in modal_action_specs(device)]
    if action_lines:
        action_lines.append("[ESC] Close")
    else:
        action_lines = ["[ESC] Close"]
    return title, lines, action_lines


def modal_action_specs(device: Dict) -> List[Tuple[int, str, str]]:
    kind = device.get("kind")
    specs: List[Tuple[int, str, str]] = []
    if kind == "ReactorUranium":
        specs.append((pygame.K_t, "[T] Toggle reactor", "toggle"))
    elif kind == "Dispenser":
        specs.append((pygame.K_t, "[T] Toggle dispenser", "toggle"))
    return specs


def handle_modal_key(
    conn: ServerConnection,
    state: ViewerState,
    snapshot: Optional[Dict],
    key: int,
) -> bool:
    if state.modal_device_id is None or not snapshot:
        return False
    interior = snapshot.get("interior") or {}
    device = find_selected_device(interior, state.modal_device_id)
    if not device:
        state.modal_device_id = None
        return False
    kind = device.get("kind")
    if kind == "NavStation":
        return handle_nav_modal_keypress(state, key)
    if kind == "ShipComputer":
        return handle_ship_computer_modal_key(conn, state, snapshot, key)
    for action_key, _, action_name in modal_action_specs(device):
        if key == action_key:
            send_device_action(conn, int(device.get("id", 0)), action_name)
            return True
    return False


def draw_pawn_panel(screen: pygame.Surface, interior: Dict) -> None:
    if FONT_SMALL is None or FONT_MEDIUM is None:
        return
    pawn = interior.get("pawn", {})
    needs = pawn.get("needs", {})
    health = (pawn.get("health") or {}).get("body_parts", [])
    power_summary = interior.get("power_summary") or interior.get("power") or {}
    lines = [
        f"Status: {pawn.get('status', 'Unknown')}",
        f"Hunger: {needs.get('hunger', 0.0) * 100:.0f}%",
        f"Thirst: {needs.get('thirst', 0.0) * 100:.0f}%",
        f"Rest: {needs.get('rest', 0.0) * 100:.0f}%",
        f"Suffocation: {pawn.get('suffocation_time', 0.0):.1f} s",
        f"Net power: {power_summary.get('net_kw', 0.0):+.1f} kW",
    ]
    line_height = FONT_SMALL.get_linesize()
    label_widths = [FONT_SMALL.size(line)[0] for line in lines]
    health_label_width = 0
    if health:
        health_label_width = max(FONT_SMALL.size(part.get("name", "?"))[0] for part in health)
    panel_width = max(
        label_widths + [health_label_width + BAR_WIDTH + 12 if health else 0]
    )
    panel_width += PANEL_PADDING * 2
    text_height = len(lines) * line_height
    health_section_height = 0
    if health:
        health_section_height = len(health) * (line_height + BAR_HEIGHT)
    panel_height = text_height + health_section_height + PANEL_PADDING * 2 + (8 if health else 0)
    panel_rect = pygame.Rect(
        PANEL_PADDING,
        WINDOW_HEIGHT - panel_height - PANEL_PADDING,
        panel_width,
        panel_height,
    )
    pygame.draw.rect(screen, COLORS["hud_bg"], panel_rect)
    pygame.draw.rect(screen, COLORS["hud_border"], panel_rect, width=1)
    y = panel_rect.top + PANEL_PADDING
    for line in lines:
        screen.blit(
            FONT_SMALL.render(line, True, COLORS["fg"]),
            (panel_rect.left + PANEL_PADDING, y),
        )
        y += line_height
    if health:
        y += 8
        for part in health:
            name = part.get("name", "?")
            hp = float(part.get("hp", 0.0))
            max_hp = max(1.0, float(part.get("max_hp", 1.0)))
            frac = clamp(hp / max_hp, 0.0, 1.0)
            label_surface = FONT_SMALL.render(name, True, COLORS["fg"])
            screen.blit(label_surface, (panel_rect.left + PANEL_PADDING, y))
            bar_x = panel_rect.left + PANEL_PADDING + health_label_width + 8
            bar_rect = pygame.Rect(bar_x, y + line_height - BAR_HEIGHT, BAR_WIDTH, BAR_HEIGHT)
            pygame.draw.rect(screen, COLORS["fg_dim"], bar_rect, width=1)
            fill_rect = bar_rect.inflate(-2, -2)
            fill_rect.width = int((BAR_WIDTH - 4) * frac)
            pygame.draw.rect(screen, COLORS["fg"], fill_rect)
            y += line_height


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
        if device_contains_tile(device, tx, ty):
            return device
    return None


def find_device_by_kind(interior: Dict, kind: str) -> Optional[Dict]:
    for device in interior.get("devices", []):
        if device.get("kind") == kind:
            return device
    return None


def device_contains_tile(device: Dict, tx: int, ty: int) -> bool:
    x = device.get("x", 0)
    y = device.get("y", 0)
    w = device.get("w", 1)
    h = device.get("h", 1)
    return x <= tx < x + w and y <= ty < y + h


def device_allows_modal(device: Dict) -> bool:
    return device.get("kind") in INTERACTIVE_MODAL_KINDS


def find_selected_device(interior: Dict, device_id: Optional[int]) -> Optional[Dict]:
    if device_id is None:
        return None
    for device in interior.get("devices", []):
        if device.get("id") == device_id:
            return device
    return None


def find_device_near_pawn(interior: Dict) -> Optional[Dict]:
    pawn = interior.get("pawn") or {}
    px = pawn.get("x")
    py = pawn.get("y")
    if px is None or py is None:
        return None
    best: Optional[Dict] = None
    best_dist = 999
    for device in interior.get("devices", []):
        for ty in range(int(device.get("y", 0)), int(device.get("y", 0)) + int(device.get("h", 1))):
            for tx in range(int(device.get("x", 0)), int(device.get("x", 0)) + int(device.get("w", 1))):
                dist = max(abs(int(px) - tx), abs(int(py) - ty))
                if dist <= 1 and dist < best_dist:
                    best = device
                    best_dist = dist
        if best_dist == 0:
            break
    return best


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
        lines.append(f"DM Code: {device.get('dm_code', '----')}")
    elif kind == "ShipComputer":
        lines.append(f"Online: {device.get('ship_computer_online', False)}")
    return lines


def primary_ship_body(snapshot: Dict) -> Optional[Dict]:
    for body in snapshot.get("bodies", []):
        if body.get("body_type") == "Ship":
            return body
    return None


def format_distance(meters: float) -> str:
    if meters < 1_000.0:
        return f"{meters:.0f} m"
    if meters < 1_000_000.0:
        return f"{meters / 1_000.0:.2f} km"
    if meters < 1_000_000_000.0:
        return f"{meters / 1_000_000.0:.2f} Mm"
    return f"{meters / 1_000_000_000.0:.2f} Gm"


def draw_message(screen: pygame.Surface, message: str) -> None:
    if FONT_MEDIUM is None:
        return
    surface = FONT_MEDIUM.render(message, True, COLORS["fg"])
    rect = surface.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
    screen.blit(surface, rect)


def prune_selection(state: ViewerState, interior: Dict) -> None:
    if state.selected_device_id is not None and not find_selected_device(
        interior, state.selected_device_id
    ):
        state.selected_device_id = None
    if state.modal_device_id is not None and not find_selected_device(
        interior, state.modal_device_id
    ):
        state.modal_device_id = None
    if state.context_tile is not None:
        tx, ty = state.context_tile
        width = interior.get("width", 0)
        height = interior.get("height", 0)
        if tx >= width or ty >= height:
            state.context_tile = None
            state.selected_device_id = None


def main() -> None:
    screen = init_pygame()
    conn = ServerConnection()
    state = ViewerState()
    snapshot: Optional[Dict] = None

    try:
        while True:
            if not handle_events(conn, state, snapshot):
                break

            line = conn.readline().strip()
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
        conn.close()
        pygame.quit()


if __name__ == "__main__":
    main()

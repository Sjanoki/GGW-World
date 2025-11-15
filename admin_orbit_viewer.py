#!/usr/bin/env python3
"""Admin viewer for the GGW orbital sandbox."""

import json
import math
import os
import subprocess
import sys
from collections import defaultdict, deque
from typing import Dict, Tuple

import pygame

WINDOW_SIZE = 900
MAX_TRAIL_POINTS = 300
PLANET_RADIUS_METERS = 6_371_000.0
BACKGROUND_COLOR = (5, 8, 12)
PLANET_COLOR = (30, 60, 120)
BODY_COLORS = {
    "Ship": (80, 200, 255),
    "Asteroid": (255, 200, 80),
    "Debris": (200, 80, 80),
    "Missile": (180, 180, 255),
}


def server_binary_path() -> str:
    """Return the path to the compiled ggw_world binary."""
    exe = "ggw_world.exe" if os.name == "nt" else "ggw_world"
    path = os.path.join("target", "debug", exe)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Binary '{path}' not found. Run 'cargo build --bin ggw_world' first."
        )
    return path


def launch_server() -> subprocess.Popen:
    """Start the Rust world server process."""
    path = server_binary_path()
    return subprocess.Popen(
        [path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )


def init_pygame() -> Tuple[pygame.Surface, pygame.font.Font]:
    """Initialize pygame and return the screen and font objects."""
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_SIZE, WINDOW_SIZE))
    pygame.display.set_caption("GGW Orbital Viewer")
    font = pygame.font.SysFont("consolas", 18)
    return screen, font


def handle_events() -> bool:
    """Process pygame events. Returns False when the app should quit."""
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return False
    return True


def compute_scale(snapshot: Dict) -> float:
    """Compute a dynamic scale so that all bodies fit within the viewport."""
    max_dist = PLANET_RADIUS_METERS
    for body in snapshot.get("bodies", []):
        x = body["x"]
        y = body["y"]
        dist = math.hypot(x, y)
        if dist > max_dist:
            max_dist = dist
    if max_dist <= 0:
        max_dist = 1.0
    return 0.45 * WINDOW_SIZE / max_dist


def world_to_screen(x: float, y: float, scale: float) -> Tuple[int, int]:
    """Convert world coordinates to screen coordinates."""
    center = WINDOW_SIZE // 2
    screen_x = int(center + x * scale)
    screen_y = int(center - y * scale)
    return screen_x, screen_y


def update_trails(trails: Dict[int, deque], snapshot: Dict, scale: float) -> None:
    """Update body trails with the newest snapshot positions."""
    for body in snapshot.get("bodies", []):
        px, py = world_to_screen(body["x"], body["y"], scale)
        trail = trails[body["id"]]
        trail.append((px, py))
        if len(trail) > MAX_TRAIL_POINTS:
            trail.popleft()


def draw_snapshot(
    screen: pygame.Surface,
    font: pygame.font.Font,
    snapshot: Dict,
    trails: Dict[int, deque],
    scale: float,
) -> None:
    """Render the world snapshot onto the screen."""
    screen.fill(BACKGROUND_COLOR)

    # Draw planet at origin.
    center = WINDOW_SIZE // 2
    planet_radius_px = max(2, int(PLANET_RADIUS_METERS * scale))
    pygame.draw.circle(screen, PLANET_COLOR, (center, center), planet_radius_px)

    # Draw orbit trails.
    for trail in trails.values():
        if len(trail) >= 2:
            pygame.draw.lines(screen, (80, 80, 80), False, list(trail), 1)

    # Draw bodies.
    for body in snapshot.get("bodies", []):
        color = BODY_COLORS.get(body["body_type"], (255, 255, 255))
        px, py = world_to_screen(body["x"], body["y"], scale)
        pygame.draw.circle(screen, color, (px, py), 4)

    # HUD text.
    sim_time = snapshot.get("sim_time", 0.0)
    hud = font.render(f"t = {sim_time:,.1f} s", True, (220, 220, 220))
    screen.blit(hud, (10, 10))

    pygame.display.flip()


def main() -> None:
    server = launch_server()
    screen, font = init_pygame()
    trails: Dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_TRAIL_POINTS))

    try:
        while True:
            if not handle_events():
                break

            line = server.stdout.readline() if server.stdout else ""
            if line == "":
                break
            line = line.strip()
            if not line:
                continue

            snapshot = json.loads(line)
            scale = compute_scale(snapshot)
            update_trails(trails, snapshot, scale)
            draw_snapshot(screen, font, snapshot, trails, scale)
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

# Phase 2 Validation – Interior Simulation Layer

Phase 2 focuses on the playable ship interior, atmosphere simulation, and the interactive device UIs that hook into the shared server. The current build verifies the following items.

## ✅ Confirmed Functionality
- **Shared dedicated server** – Both viewers consume the same TCP snapshots from the authoritative `ggw_world` server; no client launches its own sim instance.
- **Interior viewer polish** – The pawn renders with the required four-circle silhouette, the camera follows it without manual panning, and right-click context menus show device info or per-tile atmosphere readouts (P, O₂, N₂, CO₂).
- **Server-authoritative per-tile atmosphere** – Every floor-supporting tile stores its own gas masses, diffuses against its eight neighbors at 4 Hz, and remains active even when no clients are connected.
- **Pawn life support** – Pawns breathe directly from their tile, consume O₂, emit CO₂, and take server-side health damage when exposed to vacuum, low pressure, or high CO₂; suffocation status is streamed to the HUD.
- **Device modals** – Reactor, ShipComputer, Transponder, and NavStation all open with `E`, close via `ESC`, and expose the expected controls/status readouts. The Transponder modal now surfaces the broadcast ID and DM code.
- **NavStation radar + comms UI** – The NavStation modal renders a drawn radar (planet, ship, contacts, heading vector) plus a tabbed COMMS panel with open-channel and encrypted-DM sections that reference the ship’s DM code.
- **Doors and devices** – Interacting with doors, beds, dispensers, and other fixtures still works, and door toggles update the tile map without blocking the new atmosphere grid (door sealing will arrive in a later phase).
- **Admin/orbit viewer parity** – Hull outlines, zoom scale marker, locked camera, and shared TCP stream remain intact so orbital + interior states stay in sync.
- **Ideal-gas per-tile pressure** – Each 1×1×2 m cabin tile stores O₂/N₂/CO₂ masses drawn from `config/game_config.toml`, computes pressure via the ideal gas law at 20 °C, and exposes raw kg values plus kPa samples to the viewers.
- **Config-driven tick rate** – The server reads the atmosphere tick interval (0.25 s) from the same TOML config, runs diffusion/breathing at 4 Hz even with zero clients, and keeps the pawn suffocation timer wired to the new partial-pressure model.
- **Floor context panel in kg** – Right-clicking a floor now displays pressure in kPa plus gas masses in kilograms, matching the authoritative server snapshot.

## 🔄 Remaining Work / Future Phases
- Model airtight doors, vents, and fans so closed doors seal rooms instead of allowing free diffusion.
- Add regional/flood-fill atmosphere management so devices can target specific rooms rather than raw tiles.
- Implement range-limited, antenna-based comms plus DM code negotiation between ships.
- Expand multi-ship/multi-pawn scenarios and add more QA coverage for simultaneous interiors.

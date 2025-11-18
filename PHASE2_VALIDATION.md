# Phase 2 Validation – Interior Simulation Layer

This document captures the results of validating the merged Phase 2 features and serves as the hand-off for Phase 3.

## ✅ Confirmed Functionality
- **Shared dedicated server** – Both the interior and orbital viewers now connect to a single running `ggw_world` server over TCP (`127.0.0.1:40000`). No viewer attempts to spawn its own simulation instance. 【F:admin_orbit_viewer.py†L1-L313】【F:interior_viewer.py†L1-L720】
- **Interior viewer polish** – The 4-circle pawn rendering, device HUDs, and contextual right-click menu all work with the pawn-following camera. New ASCII-styled nav/comms modal replicates the required retro radar layout and limits `E` interactions to the four console devices. 【F:interior_viewer.py†L40-L720】
- **Orbit viewer UX** – Selecting a body locks the camera to it until the selection is cleared by clicking in empty space. Zooming is mouse-wheel-only, the scale marker is drawn in the lower-right corner, and ship hull outlines render when sufficiently zoomed in. Trails, selection info, and HUD styling retain the CRT aesthetic. 【F:admin_orbit_viewer.py†L1-L420】

## ❗ Outstanding Issues
1. **Room-based atmosphere simulation** – `ShipInterior` still stores a single `AtmosCell` for the entire ship, so gas changes apply globally and do not respect room boundaries or floor regions. Implement a flood-fill per tick that groups contiguous floor tiles into regions, each with its own `AtmosCell`, and exchange gases through open doors/vents. 【F:src/interior.rs†L79-L260】
2. **Door pressure equalization** – Because atmosphere is global, opening/closing doors does not affect localized pressure. Once regional atmospheres exist, door devices should link adjacent regions and equalize pressure by transferring mass proportionally to each region’s volume every simulation step. 【F:src/interior.rs†L784-L840】

## Recommended Next Steps
1. **Interior Atmos Regions**
   - Track a `region_id` for each tile and rebuild regions when walls/doors change.
   - Maintain a vector of `AtmosCell`s indexed by region and update `tile_atmos_sample` to read from the appropriate region.
   - Update devices (dispenser, vents, leaks) to target the pawn’s current region.
2. **Door Atmos Exchange**
   - Associate each `DoorDevice` with the region IDs on both sides.
   - During `ShipInterior::step`, if a door is open, compute the mass transfer needed to equalize pressure between the two regions over time (e.g., simple exponential decay).
   - Emit events/telemetry so UI panels can surface door-induced pressure drops for QA.

With these final items resolved, the interior simulation layer will meet all Phase 2 requirements and the team can proceed to combat & boarding (Phase 3).

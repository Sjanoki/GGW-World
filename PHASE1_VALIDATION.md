# Phase 1 Validation – Core Orbital Sandbox

Phase 1 established the shared orbital simulation, gravity well, and admin tooling that the later interior phases build upon. The following checklist captures the features that are already verified in the current codebase.

## ✅ Checklist
- [x] Accurate planet + gravity well definition, including despawn radius and clamped trajectories.
- [x] Circular and elliptical orbits for all tracked bodies with live propagation from their Kepler elements.
- [x] Thrust events immediately recompute orbital elements and update the ship’s path.
- [x] Real-time orbital simulation that steps continuously regardless of client connections.
- [x] Admin orbital viewer that locks to selections, renders hull shapes, shows the scale marker, and uses the shared TCP server.

## 🔍 How to Verify
1. Run the Rust server in TCP mode:
   ```bash
   cargo run
   ```
2. Launch the admin orbital viewer from a separate terminal:
   ```bash
   python admin_orbit_viewer.py
   ```
3. Observe the CRT-style HUD:
   - Planet outline, gravity well ring, and despawn ring should render.
   - Zoom with the mouse wheel and confirm the scale marker updates.
   - Click the ship to follow it; click empty space to release the camera.
4. Send a thrust event (e.g., via dev tooling or scripted input) and confirm the ship’s orbit updates smoothly without respawning the server.
5. Leave the viewer running for several minutes—bodies should keep advancing along their ellipses with no visible drift or reset.

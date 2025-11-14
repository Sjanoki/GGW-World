# GGW – 2D Orbital PvP Sandbox with Interior Sim and Player-Driven Economy

## Version
0.1 – Engineering-Centric GDD for Implementation

---

## 0. High-Level Overview
GGW is a persistent, multiplayer 2D orbital sandbox set around a single Earth-sized exoplanet orbiting a dead star. The game combines:

- KSP-style 2D patched-conic orbits (single gravity source, no SOIs)
- SS13/Ostranauts-style interior ship simulation (2D grid, rooms, atmosphere, power, hull breaches)
- RimWorld-style biological player characters (organs, wounds, needs)
- Starsector-style combat (weapons, shields, missiles)
- EVE-like economy (player-driven, no NPCs, no artificial sinks)
- Bitcoin-miner-based currency (energy → BTC, no money from thin air)

Everything is PvP. There are no NPC ships or stations, only player-built ships and “stations” (large ships). Safe zones exist only where players build enough defenses (turrets driven by AI computers).

---

## 1. Core Pillars
1. **Physics & Movement** – 2D patched-conic Kepler orbits with analytic burns.
2. **Interior Survival** – SS13-style tile ships with atmosphere and power management.
3. **Player Biology** – RimWorld-inspired pawns with organs and needs.
4. **PvP Combat & Boarding** – Starsector-like weapon systems and boarding gameplay.
5. **Economy & Industry** – Fully player-driven economy with Bitcoin miners.
6. **Persistent Multiplayer** – Player-defined safety through defenses in a shared world.
7. **Time & Scale** – Real-time, Earth-scale orbits with rare new bodies.

---

## 2. World & Scope
- Single system with one gravity source.
- Entities include ships, asteroids, debris, and missiles.
- Sensor-based fog of war with “running dark” tactics.

---

## 3. Physics Layer
### 3.1 Coordinate System & Units
- 2D plane, meters, seconds, kilograms.
- Analytic Kepler solutions with planet GM constant.

### 3.2 Orbital State Representation
```
struct OrbitState {
    semi_major_axis: f64,
    eccentricity: f64,
    arg_of_periapsis: f64,
    mean_anomaly_at_epoch: f64,
    epoch: f64,
}

struct BodyState {
    id: u64,
    mass: f64,
    radius: f64,
    orbit: OrbitState,
    position: Vec2,
    velocity: Vec2,
    body_type: BodyType,
}
```

### 3.3 Thrust & Engine Model
- RCS, Chemical (instant ΔV), Ion (pulsed ΔV) thrust events.
- Thrust events recompute orbital elements after velocity changes.

### 3.4 Collisions
- Discrete collision windows every Δt seconds.
- Broad-phase spatial partitioning, kinetic energy damage, debris spawn.

### 3.5 Time Management
- Global `sim_time`, fixed Δt ticks for collisions and interiors.

### 3.6 Precision & Scaling
- Double precision for orbital math, separate local interior grids.

---

## 4. Ship & Interior Simulation
### 4.1 Ship Topology
Ships contain grid tiles, hull, devices, docks, and networks.

### 4.2 Atmosphere, Pressure, Temperature
- Atmos cells per tile with pressure, temperature, gas mix.
- Hull breaches vent to vacuum; life support maintains environment.

### 4.3 Power & Resource Networks
- Devices produce/consume power with priority-based brownouts.

### 4.4 Player Avatar & Stats
- Pawns with body parts, health, needs, inventory, skills, statuses.

### 4.5 Sleep & Logoff
- Needs freeze only when sleeping in bed; sleepers remain vulnerable.

### 4.6 Docking & Stations
- Dock ports, optional power/atmos links, clone vats for respawn.

---

## 5. Combat & Damage Model
- Lasers (hitscan), bullets (projectiles), missiles (Kepler + burns).
- Energy shields with strength/recharge.
- AI computers run turret firing rules.
- Damage can breach hulls, vent atmosphere, harm players.
- Boarding via docks or breaches.

---

## 6. Economy & Industry
- Resources: ore, fissiles, fuel, xenon, components.
- Energy via nuclear or fuel generators.
- Bitcoin miners generate the only currency by consuming energy.
- Player-run markets with no NPC orders or artificial sinks.

---

## 7. Multiplayer & Persistence
- Authoritative server simulating orbital and interior layers.
- Persistent ships, markets, clone vats, BTC wallets.
- Sleep/logoff rules keep pawns in world.

---

## 8. Tools & Debug
- Admin orbit viewer for spawning bodies and editing orbits.
- Debug overlays for queues, atmos, power networks.
- Structured logging for major events.

---

## 9. Implementation Roadmap
1. **Phase 1 – Core Orbital Sandbox**
2. **Phase 2 – Interior & Pawn Simulation**
3. **Phase 3 – Combat & Boarding**
4. **Phase 4 – Economy & Industry**
5. **Phase 5 – Stations, Clone Vats & Social Structures**
6. **Phase 6 – Polishing & Extended Features**

---

## 10. Notes
- This document is the source of truth for physics, interiors, economy, combat, and multiplayer.
- When implementing modules, reference the relevant sections for specifications.

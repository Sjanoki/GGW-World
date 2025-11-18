use std::collections::VecDeque;

use crate::{
    config::{AtmosphereConfig, GameConfig},
    HullShape, Vec2, TILE_SIZE_METERS,
};

const IDEAL_GAS_R: f64 = 8.314_462_618;
const ATMOS_DIFFUSION_COEFF: f32 = 0.4;
const ATMOS_DIFFUSION_MAX_FRACTION: f32 = 0.5;
const O2_CONSUMPTION_KG_PER_SEC: f32 = 0.0003;
const CO2_PRODUCTION_KG_PER_SEC: f32 = 0.0003;
const LOW_PRESSURE_THRESHOLD_KPA: f32 = 70.0;
const LOW_O2_PARTIAL_PRESSURE_KPA: f32 = 16.0;
const HIGH_CO2_PARTIAL_PRESSURE_KPA: f32 = 8.0;
const SUFFOCATION_DAMAGE_PER_SEC: f32 = 2.0;
const VACUUM_DAMAGE_PER_SEC: f32 = 8.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TileType {
    Empty,
    Floor,
    Wall,
    Bed,
    DoorClosed,
    DoorOpen,
}

#[derive(Clone, Debug)]
pub struct Tile {
    pub tile_type: TileType,
}

impl Tile {
    pub fn new(tile_type: TileType) -> Self {
        Self { tile_type }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GasType {
    O2,
    N2,
    CO2,
    Xenon,
}

impl GasType {
    pub fn config_key(&self) -> &'static str {
        match self {
            GasType::O2 => "O2",
            GasType::N2 => "N2",
            GasType::CO2 => "CO2",
            GasType::Xenon => "Xenon",
        }
    }

    pub fn from_name(name: &str) -> Option<Self> {
        match name.to_ascii_uppercase().as_str() {
            "O2" => Some(GasType::O2),
            "N2" => Some(GasType::N2),
            "CO2" => Some(GasType::CO2),
            "XENON" => Some(GasType::Xenon),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct AtmosSample {
    pub pressure_kpa: f32,
    pub o2_kg: f32,
    pub n2_kg: f32,
    pub co2_kg: f32,
}

#[derive(Clone, Debug)]
pub struct TileAtmosphere {
    pub o2_kg: f32,
    pub n2_kg: f32,
    pub co2_kg: f32,
    pub temp_c: f32,
}

#[derive(Clone, Copy, Debug, Default)]
struct GasDelta {
    o2_kg: f32,
    n2_kg: f32,
    co2_kg: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct GasTotals {
    pub o2_kg: f32,
    pub n2_kg: f32,
    pub co2_kg: f32,
}

impl TileAtmosphere {
    pub fn new(o2_kg: f32, n2_kg: f32, co2_kg: f32, temp_c: f32) -> Self {
        Self {
            o2_kg,
            n2_kg,
            co2_kg,
            temp_c,
        }
    }

    pub fn vacuum(temp_c: f32) -> Self {
        Self {
            o2_kg: 0.0,
            n2_kg: 0.0,
            co2_kg: 0.0,
            temp_c,
        }
    }

    pub fn with_standard_air(cfg: &AtmosphereConfig) -> Self {
        Self {
            o2_kg: cfg
                .gases
                .get("O2")
                .map(|g| g.default_mass_kg)
                .unwrap_or(0.0),
            n2_kg: cfg
                .gases
                .get("N2")
                .map(|g| g.default_mass_kg)
                .unwrap_or(0.0),
            co2_kg: cfg
                .gases
                .get("CO2")
                .map(|g| g.default_mass_kg)
                .unwrap_or(0.0),
            temp_c: cfg.baseline_temp_c,
        }
    }

    pub fn sample(&self, cfg: &AtmosphereConfig) -> AtmosSample {
        AtmosSample {
            pressure_kpa: self.pressure_kpa(cfg),
            o2_kg: self.o2_kg,
            n2_kg: self.n2_kg,
            co2_kg: self.co2_kg,
        }
    }

    pub fn total_mass(&self) -> f32 {
        self.o2_kg + self.n2_kg + self.co2_kg
    }

    pub fn add_gas(&mut self, gas: GasType, mass: f32) {
        if mass <= 0.0 {
            return;
        }
        match gas {
            GasType::O2 => self.o2_kg += mass,
            GasType::N2 => self.n2_kg += mass,
            GasType::CO2 => self.co2_kg += mass,
            GasType::Xenon => {}
        }
    }

    pub fn clamp_non_negative(&mut self) {
        self.o2_kg = self.o2_kg.max(0.0);
        self.n2_kg = self.n2_kg.max(0.0);
        self.co2_kg = self.co2_kg.max(0.0);
        if self.total_mass() < 1e-6 {
            self.o2_kg = 0.0;
            self.n2_kg = 0.0;
            self.co2_kg = 0.0;
        }
    }

    fn total_moles(&self, cfg: &AtmosphereConfig) -> f64 {
        let o2 = self.moles_for("O2", cfg);
        let n2 = self.moles_for("N2", cfg);
        let co2 = self.moles_for("CO2", cfg);
        o2 + n2 + co2
    }

    fn moles_for(&self, gas_key: &str, cfg: &AtmosphereConfig) -> f64 {
        let mass = match gas_key {
            "O2" => self.o2_kg as f64,
            "N2" => self.n2_kg as f64,
            "CO2" => self.co2_kg as f64,
            _ => 0.0,
        };
        let molar_mass = cfg
            .gases
            .get(gas_key)
            .map(|g| g.molar_mass_kg_per_mol as f64)
            .unwrap_or(1.0_f64);
        if molar_mass <= 0.0 {
            0.0
        } else {
            mass / molar_mass
        }
    }

    pub fn pressure_kpa(&self, cfg: &AtmosphereConfig) -> f32 {
        let total_moles = self.total_moles(cfg);
        if total_moles <= f64::EPSILON {
            return 0.0;
        }
        let temp_k = (self.temp_c as f64 + 273.15).max(1.0);
        let volume_m3 = (cfg.tile_size_m * cfg.tile_size_m * cfg.tile_height_m) as f64;
        let pressure_pa = total_moles * IDEAL_GAS_R * temp_k / volume_m3.max(1e-6);
        (pressure_pa / 1000.0) as f32
    }

    pub fn partial_pressure_kpa(&self, gas: GasType, cfg: &AtmosphereConfig) -> f32 {
        let key = gas.config_key();
        let moles = self.moles_for(key, cfg);
        if moles <= f64::EPSILON {
            return 0.0;
        }
        let temp_k = (self.temp_c as f64 + 273.15).max(1.0);
        let volume_m3 = (cfg.tile_size_m * cfg.tile_size_m * cfg.tile_height_m) as f64;
        let pressure_pa = moles * IDEAL_GAS_R * temp_k / volume_m3.max(1e-6);
        (pressure_pa / 1000.0) as f32
    }
}

impl Default for TileAtmosphere {
    fn default() -> Self {
        Self {
            o2_kg: 0.0,
            n2_kg: 0.0,
            co2_kg: 0.0,
            temp_c: 0.0,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct PowerState {
    pub net_kw: f32,
    pub total_production_kw: f32,
    pub total_consumption_kw: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DeviceType {
    Tank,
    ReactorUranium,
    Dispenser,
    NavStation,
    Transponder,
    ShipComputer,
    BedDevice,
    Toilet,
    FoodGenerator,
    RCSThruster,
    Light,
    DoorDevice,
    PowerLine,
    GasLine,
}

#[derive(Clone, Debug)]
pub struct Device {
    pub id: u64,
    pub device_type: DeviceType,
    pub x: u32,
    pub y: u32,
    pub w: u32,
    pub h: u32,
    pub power_kw: f32,
    pub online: bool,
    pub data: DeviceData,
}

#[derive(Clone, Debug)]
pub enum DeviceData {
    Tank(TankData),
    Reactor(ReactorData),
    Dispenser(DispenserData),
    NavStation(NavStationData),
    Transponder(TransponderData),
    ShipComputer(ShipComputerData),
    BedDevice(BedDeviceData),
    Toilet(ToiletData),
    FoodGenerator(FoodGeneratorData),
    RCSThruster(RCSThrusterData),
    Light(LightData),
    DoorDevice(DoorDeviceData),
    PowerLine(PowerLineData),
    GasLine(GasLineData),
}

#[derive(Clone, Debug)]
pub struct TankData {
    pub capacity_kg: f32,
    pub o2_kg: f32,
    pub n2_kg: f32,
    pub co2_kg: f32,
    pub xenon_kg: f32,
}

#[derive(Clone, Debug)]
pub struct ReactorData {
    pub fuel_kg: f32,
    pub max_fuel_kg: f32,
    pub fuel_burn_rate_kg_per_s: f32,
    pub power_output_kw: f32,
    pub online: bool,
}

#[derive(Clone, Debug)]
pub struct DispenserData {
    pub active: bool,
    pub rate_kg_per_s: f32,
    pub gas_type: GasType,
    pub connected_tank_id: Option<u64>,
}

#[derive(Clone, Debug)]
pub struct NavStationData {
    pub online: bool,
}

#[derive(Clone, Debug)]
pub struct TransponderData {
    pub callsign: String,
    pub online: bool,
    pub dm_code: u32,
}

#[derive(Clone, Debug)]
pub struct ShipComputerData {
    pub online: bool,
}

#[derive(Clone, Debug)]
pub struct BedDeviceData {}

#[derive(Clone, Debug)]
pub struct ToiletData {}

#[derive(Clone, Debug)]
pub struct FoodGeneratorData {
    pub food_units: f32,
    pub max_food_units: f32,
    pub online: bool,
}

#[derive(Clone, Debug)]
pub struct RCSThrusterData {
    pub uses_any_gas: bool,
    pub preferred_gas: GasType,
    pub online: bool,
}

#[derive(Clone, Debug)]
pub struct LightData {
    pub intensity: f32,
    pub online: bool,
}

#[derive(Clone, Debug)]
pub struct DoorDeviceData {
    pub open: bool,
}

#[derive(Clone, Debug)]
pub struct PowerLineData {}

#[derive(Clone, Debug)]
pub struct GasLineData {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PawnStatus {
    Awake,
    Sleeping,
}

#[derive(Clone, Copy, Debug)]
pub struct NeedsState {
    pub hunger: f32,
    pub thirst: f32,
    pub rest: f32,
}

impl NeedsState {
    pub fn new() -> Self {
        Self {
            hunger: 0.0,
            thirst: 0.0,
            rest: 0.0,
        }
    }

    fn clamp(&mut self) {
        self.hunger = self.hunger.clamp(0.0, 1.0);
        self.thirst = self.thirst.clamp(0.0, 1.0);
        self.rest = self.rest.clamp(0.0, 1.0);
    }
}

#[derive(Clone, Debug)]
pub struct Pawn {
    pub id: u64,
    pub name: String,
    pub x: u32,
    pub y: u32,
    pub status: PawnStatus,
    pub needs: NeedsState,
    pub health: HealthState,
    pub suffocation_time: f32,
}

#[derive(Clone, Debug)]
pub struct BodyPart {
    pub name: String,
    pub hp: f32,
    pub max_hp: f32,
    pub vital: bool,
}

#[derive(Clone, Debug)]
pub struct HealthState {
    pub body_parts: Vec<BodyPart>,
}

impl HealthState {
    pub fn new_default() -> Self {
        let mut body_parts = Vec::new();
        let parts = [
            ("Head", 30.0, true),
            ("Torso", 40.0, true),
            ("Left Arm", 25.0, false),
            ("Right Arm", 25.0, false),
            ("Left Leg", 35.0, false),
            ("Right Leg", 35.0, false),
        ];
        for (name, max_hp, vital) in parts {
            body_parts.push(BodyPart {
                name: name.to_string(),
                hp: max_hp,
                max_hp,
                vital,
            });
        }
        Self { body_parts }
    }
}

#[derive(Clone, Debug)]
pub struct ShipInterior {
    pub width: u32,
    pub height: u32,
    pub tiles: Vec<Tile>,
    pub tile_atmos: Vec<TileAtmosphere>,
    pub power: PowerState,
    pub devices: Vec<Device>,
    pub hull_shape: HullShape,
}

impl ShipInterior {
    pub fn new_test_layout(config: &GameConfig) -> Self {
        let width = 12;
        let height = 8;
        let mut tiles = vec![Tile::new(TileType::Floor); (width * height) as usize];
        // outer walls
        for x in 0..width {
            let top = Self::idx(x, 0, width);
            let bottom = Self::idx(x, height - 1, width);
            tiles[top].tile_type = TileType::Wall;
            tiles[bottom].tile_type = TileType::Wall;
        }
        for y in 0..height {
            let left = Self::idx(0, y, width);
            let right = Self::idx(width - 1, y, width);
            tiles[left].tile_type = TileType::Wall;
            tiles[right].tile_type = TileType::Wall;
        }
        // doorway at center of bottom wall
        let door_x = width / 2;
        let door_y = height - 1;
        tiles[Self::idx(door_x, door_y, width)].tile_type = TileType::DoorOpen;
        // bed area occupies two tiles
        tiles[Self::idx(2, 2, width)].tile_type = TileType::Bed;
        tiles[Self::idx(3, 2, width)].tile_type = TileType::Bed;

        let atmos_cfg = &config.atmosphere;
        let mut tile_atmos =
            vec![TileAtmosphere::vacuum(atmos_cfg.baseline_temp_c); (width * height) as usize];
        for y in 0..height {
            for x in 0..width {
                let idx = Self::idx(x, y, width);
                if Self::tile_supports_atmos(tiles[idx].tile_type) {
                    tile_atmos[idx] = TileAtmosphere::with_standard_air(atmos_cfg);
                }
            }
        }
        let power = PowerState::default();
        let mut devices = Vec::new();
        let mut next_id = 1u64;

        let nav_power = config
            .items
            .get("nav_station")
            .map(|item| item.idle_power_kw)
            .unwrap_or(1.5);
        let ship_computer_power = config
            .items
            .get("ship_computer")
            .map(|item| item.idle_power_kw)
            .unwrap_or(2.5);
        let transponder_power = config
            .items
            .get("transponder")
            .map(|item| item.idle_power_kw)
            .unwrap_or(5.0);
        let light_power = config
            .items
            .get("light")
            .map(|item| item.idle_power_kw)
            .unwrap_or(1.0);
        let dispenser_rate = config
            .items
            .get("dispenser")
            .and_then(|item| item.flow_kg_per_s)
            .unwrap_or(0.01);
        let dispenser_gas = config
            .items
            .get("dispenser")
            .and_then(|item| item.gas_type.as_deref())
            .and_then(GasType::from_name)
            .unwrap_or(GasType::O2);

        devices.push(Device {
            id: next_id,
            device_type: DeviceType::ReactorUranium,
            x: 5,
            y: 2,
            w: 3,
            h: 3,
            power_kw: 0.0,
            online: true,
            data: DeviceData::Reactor(ReactorData {
                fuel_kg: 100.0,
                max_fuel_kg: 100.0,
                fuel_burn_rate_kg_per_s: 0.0005,
                power_output_kw: 500.0,
                online: true,
            }),
        });
        next_id += 1;

        devices.push(Device {
            id: next_id,
            device_type: DeviceType::Tank,
            x: 3,
            y: 4,
            w: 1,
            h: 1,
            power_kw: 0.0,
            online: true,
            data: DeviceData::Tank(TankData {
                capacity_kg: 200.0,
                o2_kg: 80.0,
                n2_kg: 100.0,
                co2_kg: 5.0,
                xenon_kg: 10.0,
            }),
        });
        let tank_id = next_id;
        next_id += 1;

        devices.push(Device {
            id: next_id,
            device_type: DeviceType::Dispenser,
            x: 4,
            y: 4,
            w: 1,
            h: 1,
            power_kw: config
                .items
                .get("dispenser")
                .map(|item| item.idle_power_kw)
                .unwrap_or(2.0),
            online: true,
            data: DeviceData::Dispenser(DispenserData {
                active: true,
                rate_kg_per_s: dispenser_rate,
                gas_type: dispenser_gas,
                connected_tank_id: Some(tank_id),
            }),
        });
        next_id += 1;

        devices.push(Device {
            id: next_id,
            device_type: DeviceType::Light,
            x: 2,
            y: 5,
            w: 1,
            h: 1,
            power_kw: light_power,
            online: true,
            data: DeviceData::Light(LightData {
                intensity: 1.0,
                online: true,
            }),
        });
        next_id += 1;

        devices.push(Device {
            id: next_id,
            device_type: DeviceType::Transponder,
            x: 8,
            y: 1,
            w: 2,
            h: 1,
            power_kw: transponder_power,
            online: true,
            data: DeviceData::Transponder(TransponderData {
                callsign: "GGW-TEST".to_string(),
                online: true,
                dm_code: 4242,
            }),
        });
        next_id += 1;

        devices.push(Device {
            id: next_id,
            device_type: DeviceType::NavStation,
            x: 8,
            y: 3,
            w: 2,
            h: 1,
            power_kw: nav_power,
            online: true,
            data: DeviceData::NavStation(NavStationData { online: true }),
        });
        next_id += 1;

        devices.push(Device {
            id: next_id,
            device_type: DeviceType::ShipComputer,
            x: 8,
            y: 5,
            w: 2,
            h: 1,
            power_kw: ship_computer_power,
            online: true,
            data: DeviceData::ShipComputer(ShipComputerData { online: true }),
        });

        next_id += 1;
        devices.push(Device {
            id: next_id,
            device_type: DeviceType::BedDevice,
            x: 2,
            y: 2,
            w: 2,
            h: 1,
            power_kw: 0.0,
            online: true,
            data: DeviceData::BedDevice(BedDeviceData {}),
        });

        next_id += 1;
        devices.push(Device {
            id: next_id,
            device_type: DeviceType::DoorDevice,
            x: door_x,
            y: door_y,
            w: 1,
            h: 1,
            power_kw: 0.0,
            online: true,
            data: DeviceData::DoorDevice(DoorDeviceData { open: true }),
        });

        next_id += 1;
        devices.push(Device {
            id: next_id,
            device_type: DeviceType::FoodGenerator,
            x: 4,
            y: 2,
            w: 1,
            h: 1,
            power_kw: 3.0,
            online: true,
            data: DeviceData::FoodGenerator(FoodGeneratorData {
                food_units: 5.0,
                max_food_units: 5.0,
                online: true,
            }),
        });

        let mut ship = Self {
            width,
            height,
            tiles,
            tile_atmos,
            power,
            devices,
            hull_shape: HullShape {
                vertices: Vec::new(),
            },
        };
        ship.rebuild_hull_shape();
        ship
    }

    fn idx(x: u32, y: u32, width: u32) -> usize {
        (y * width + x) as usize
    }

    pub fn in_bounds(&self, x: i32, y: i32) -> bool {
        x >= 0 && y >= 0 && (x as u32) < self.width && (y as u32) < self.height
    }

    pub fn tile(&self, x: u32, y: u32) -> Option<&Tile> {
        if x < self.width && y < self.height {
            Some(&self.tiles[Self::idx(x, y, self.width)])
        } else {
            None
        }
    }

    pub fn tile_type(&self, x: u32, y: u32) -> TileType {
        self.tile(x, y)
            .map(|t| t.tile_type)
            .unwrap_or(TileType::Empty)
    }

    fn tile_supports_atmos(tile_type: TileType) -> bool {
        matches!(
            tile_type,
            TileType::Floor | TileType::Bed | TileType::DoorOpen | TileType::DoorClosed
        )
    }

    pub fn tile_atmos_sample(
        &self,
        x: u32,
        y: u32,
        atmos_cfg: &AtmosphereConfig,
    ) -> Option<AtmosSample> {
        if !self.in_bounds(x as i32, y as i32) {
            return None;
        }
        let tile_type = self.tile_type(x, y);
        if !Self::tile_supports_atmos(tile_type) {
            return None;
        }
        let idx = Self::idx(x, y, self.width);
        Some(self.tile_atmos[idx].sample(atmos_cfg))
    }

    pub fn tile_atmos_cell(&self, x: u32, y: u32) -> Option<&TileAtmosphere> {
        if !self.in_bounds(x as i32, y as i32) {
            return None;
        }
        if !Self::tile_supports_atmos(self.tile_type(x, y)) {
            return None;
        }
        let idx = Self::idx(x, y, self.width);
        Some(&self.tile_atmos[idx])
    }

    pub fn tile_atmos_cell_mut(&mut self, x: u32, y: u32) -> Option<&mut TileAtmosphere> {
        if !self.in_bounds(x as i32, y as i32) {
            return None;
        }
        if !Self::tile_supports_atmos(self.tile_type(x, y)) {
            return None;
        }
        let idx = Self::idx(x, y, self.width);
        Some(&mut self.tile_atmos[idx])
    }

    pub fn is_passable(&self, x: i32, y: i32) -> bool {
        if !self.in_bounds(x, y) {
            return false;
        }
        match self.tile_type(x as u32, y as u32) {
            TileType::Floor | TileType::Bed | TileType::DoorOpen => true,
            _ => false,
        }
    }

    pub fn set_tile_type(
        &mut self,
        x: u32,
        y: u32,
        tile_type: TileType,
        atmos_cfg: &AtmosphereConfig,
    ) {
        if x < self.width && y < self.height {
            let idx = Self::idx(x, y, self.width);
            self.tiles[idx].tile_type = tile_type;
            if !Self::tile_supports_atmos(tile_type) {
                self.tile_atmos[idx] = TileAtmosphere::vacuum(atmos_cfg.baseline_temp_c);
            } else if self.tile_atmos[idx].total_mass() <= f32::EPSILON {
                self.tile_atmos[idx] = TileAtmosphere::with_standard_air(atmos_cfg);
            }
        }
    }

    pub fn total_atmos(&self) -> GasTotals {
        let mut total = GasTotals::default();
        for cell in &self.tile_atmos {
            total.o2_kg += cell.o2_kg;
            total.n2_kg += cell.n2_kg;
            total.co2_kg += cell.co2_kg;
        }
        total
    }

    fn pick_device_output_tile(&self, rect: (u32, u32, u32, u32)) -> Option<(u32, u32)> {
        let (x, y, w, h) = rect;
        let front_y = y + h;
        if front_y < self.height {
            for tx in x..(x + w).min(self.width) {
                if Self::tile_supports_atmos(self.tile_type(tx, front_y)) {
                    return Some((tx, front_y));
                }
            }
        }
        for ty in y..(y + h).min(self.height) {
            for tx in x..(x + w).min(self.width) {
                if Self::tile_supports_atmos(self.tile_type(tx, ty)) {
                    return Some((tx, ty));
                }
            }
        }
        None
    }

    fn inject_gas_into_tile(&mut self, x: u32, y: u32, gas: GasType, mass: f32) {
        if mass <= 0.0 {
            return;
        }
        if let Some(cell) = self.tile_atmos_cell_mut(x, y) {
            cell.add_gas(gas, mass);
        }
    }

    fn rebuild_hull_shape(&mut self) {
        let mut edges = Vec::new();
        for y in 0..self.height {
            for x in 0..self.width {
                let idx = Self::idx(x, y, self.width);
                if !Self::is_hull_tile(self.tiles[idx].tile_type) {
                    continue;
                }
                let xi = x as i32;
                let yi = y as i32;
                let neighbors = [
                    ((0, -1), (xi, yi), (xi + 1, yi)),
                    ((1, 0), (xi + 1, yi), (xi + 1, yi + 1)),
                    ((0, 1), (xi + 1, yi + 1), (xi, yi + 1)),
                    ((-1, 0), (xi, yi + 1), (xi, yi)),
                ];
                for (offset, start, end) in neighbors {
                    let nx = x as i32 + offset.0;
                    let ny = y as i32 + offset.1;
                    let neighbor_in_bounds =
                        nx >= 0 && ny >= 0 && (nx as u32) < self.width && (ny as u32) < self.height;
                    let neighbor_is_hull = if neighbor_in_bounds {
                        let n_idx = Self::idx(nx as u32, ny as u32, self.width);
                        Self::is_hull_tile(self.tiles[n_idx].tile_type)
                    } else {
                        false
                    };
                    if !neighbor_is_hull {
                        edges.push(((start.0, start.1), (end.0, end.1)));
                    }
                }
            }
        }

        if edges.is_empty() {
            self.hull_shape = Self::rectangular_hull(self.width, self.height);
            return;
        }

        let mut polygon_points = Vec::new();
        let mut remaining = edges;
        let mut current = remaining[0].0;
        polygon_points.push(current);
        let mut guard = 0;
        while !remaining.is_empty() && guard < 10_000 {
            guard += 1;
            if let Some(idx) = remaining.iter().position(|edge| edge.0 == current) {
                let edge = remaining.remove(idx);
                current = edge.1;
                polygon_points.push(current);
                if current == polygon_points[0] {
                    break;
                }
            } else {
                break;
            }
        }

        if polygon_points.len() < 4 || current != polygon_points[0] {
            self.hull_shape = Self::rectangular_hull(self.width, self.height);
            return;
        }

        if let (Some(first), Some(last)) = (polygon_points.first(), polygon_points.last()) {
            if first == last {
                polygon_points.pop();
            }
        }

        let center_x = (self.width as f64 * TILE_SIZE_METERS) / 2.0;
        let center_y = (self.height as f64 * TILE_SIZE_METERS) / 2.0;
        let vertices = polygon_points
            .into_iter()
            .map(|(px, py)| {
                let x = px as f64 * TILE_SIZE_METERS - center_x;
                let y = center_y - py as f64 * TILE_SIZE_METERS;
                Vec2::new(x, y)
            })
            .collect();
        self.hull_shape = HullShape { vertices };
    }

    fn rectangular_hull(width: u32, height: u32) -> HullShape {
        let w = width as f64 * TILE_SIZE_METERS / 2.0;
        let h = height as f64 * TILE_SIZE_METERS / 2.0;
        HullShape {
            vertices: vec![
                Vec2::new(-w, h),
                Vec2::new(w, h),
                Vec2::new(w, -h),
                Vec2::new(-w, -h),
            ],
        }
    }

    fn is_hull_tile(tile_type: TileType) -> bool {
        matches!(
            tile_type,
            TileType::Wall | TileType::DoorClosed | TileType::DoorOpen
        )
    }

    pub fn step(&mut self, dt: f64) {
        self.power.total_production_kw = 0.0;
        self.power.total_consumption_kw = 0.0;
        let dt_f32 = dt as f32;

        let device_count = self.devices.len();
        for idx in 0..device_count {
            let (before, rest) = self.devices.split_at_mut(idx);
            let (device, after) = rest.split_first_mut().expect("split_first");
            let device_rect = (device.x, device.y, device.w, device.h);
            let mut pending_injection: Option<((u32, u32, u32, u32), GasType, f32)> = None;

            if device.online && device.power_kw > 0.0 {
                self.power.total_consumption_kw += device.power_kw;
            } else if device.online && device.power_kw < 0.0 {
                self.power.total_production_kw += -device.power_kw;
            }

            match &mut device.data {
                DeviceData::Reactor(data) => {
                    if data.online && data.fuel_kg > 0.0 {
                        self.power.total_production_kw += data.power_output_kw;
                        let burn = (data.fuel_burn_rate_kg_per_s * dt_f32).min(data.fuel_kg);
                        data.fuel_kg -= burn;
                        if data.fuel_kg <= 0.0 {
                            data.fuel_kg = 0.0;
                            data.online = false;
                        }
                    }
                }
                DeviceData::Dispenser(data) => {
                    if !device.online || !data.active {
                        continue;
                    }
                    let transfer = data.rate_kg_per_s * dt_f32;
                    if transfer <= 0.0 {
                        continue;
                    }
                    if let Some(tank_id) = data.connected_tank_id {
                        let mut iter = before.iter_mut().chain(after.iter_mut());
                        if let Some(tank_device) = iter.find(|d| d.id == tank_id) {
                            if let DeviceData::Tank(tank) = &mut tank_device.data {
                                let moved = match data.gas_type {
                                    GasType::O2 => {
                                        let moved = tank.o2_kg.min(transfer);
                                        tank.o2_kg -= moved;
                                        moved
                                    }
                                    GasType::N2 => {
                                        let moved = tank.n2_kg.min(transfer);
                                        tank.n2_kg -= moved;
                                        moved
                                    }
                                    GasType::CO2 => {
                                        let moved = tank.co2_kg.min(transfer);
                                        tank.co2_kg -= moved;
                                        moved
                                    }
                                    GasType::Xenon => {
                                        let moved = tank.xenon_kg.min(transfer);
                                        tank.xenon_kg -= moved;
                                        0.0
                                    }
                                };
                                if moved > 0.0 {
                                    pending_injection = Some((device_rect, data.gas_type, moved));
                                }
                            }
                        }
                    }
                }
                _ => {}
            }

            if let Some((rect, gas, mass)) = pending_injection.take() {
                if let Some((tx, ty)) = self.pick_device_output_tile(rect) {
                    self.inject_gas_into_tile(tx, ty, gas, mass);
                }
            }
        }

        self.power.net_kw = self.power.total_production_kw - self.power.total_consumption_kw;
    }

    pub fn step_atmosphere(&mut self, dt: f32) {
        if dt <= 0.0 {
            return;
        }
        let width = self.width as i32;
        let height = self.height as i32;
        let factor = (ATMOS_DIFFUSION_COEFF * dt).min(ATMOS_DIFFUSION_MAX_FRACTION);
        if factor <= 0.0 {
            return;
        }
        let mut deltas = vec![GasDelta::default(); self.tile_atmos.len()];
        const NEIGHBORS: &[(i32, i32)] = &[(1, 0), (0, 1), (1, 1), (-1, 1)];
        for y in 0..height {
            for x in 0..width {
                let idx_a = Self::idx(x as u32, y as u32, self.width);
                if !Self::tile_supports_atmos(self.tiles[idx_a].tile_type) {
                    continue;
                }
                for (dx, dy) in NEIGHBORS {
                    let nx = x + dx;
                    let ny = y + dy;
                    if nx < 0 || ny < 0 || nx >= width || ny >= height {
                        continue;
                    }
                    let idx_b = Self::idx(nx as u32, ny as u32, self.width);
                    if !Self::tile_supports_atmos(self.tiles[idx_b].tile_type) {
                        continue;
                    }
                    let cell_a = self.tile_atmos[idx_a].clone();
                    let cell_b = self.tile_atmos[idx_b].clone();
                    let delta_o2 = (cell_b.o2_kg - cell_a.o2_kg) * factor;
                    let delta_n2 = (cell_b.n2_kg - cell_a.n2_kg) * factor;
                    let delta_co2 = (cell_b.co2_kg - cell_a.co2_kg) * factor;
                    deltas[idx_a].o2_kg += delta_o2;
                    deltas[idx_b].o2_kg -= delta_o2;
                    deltas[idx_a].n2_kg += delta_n2;
                    deltas[idx_b].n2_kg -= delta_n2;
                    deltas[idx_a].co2_kg += delta_co2;
                    deltas[idx_b].co2_kg -= delta_co2;
                }
            }
        }
        for (cell, delta) in self.tile_atmos.iter_mut().zip(deltas.into_iter()) {
            cell.o2_kg += delta.o2_kg;
            cell.n2_kg += delta.n2_kg;
            cell.co2_kg += delta.co2_kg;
            cell.clamp_non_negative();
        }
    }
}

#[derive(Clone, Debug)]
pub struct InteriorWorld {
    pub ship: ShipInterior,
    pub pawn: Pawn,
    command_queue: VecDeque<InteriorCommand>,
    atmos_accumulator: f64,
}

impl InteriorWorld {
    pub fn new_test_ship(config: &GameConfig) -> Self {
        let ship = ShipInterior::new_test_layout(config);
        let pawn = Pawn {
            id: 1,
            name: "Test Pawn".to_string(),
            x: 2,
            y: 3,
            status: PawnStatus::Awake,
            needs: NeedsState::new(),
            health: HealthState::new_default(),
            suffocation_time: 0.0,
        };
        Self {
            ship,
            pawn,
            command_queue: VecDeque::new(),
            atmos_accumulator: 0.0,
        }
    }

    pub fn queue_command(&mut self, command: InteriorCommand) {
        self.command_queue.push_back(command);
    }

    pub fn step(&mut self, dt: f64, config: &GameConfig) {
        self.process_commands(config);
        self.ship.step(dt);
        self.update_pawn_needs(dt);
        self.atmos_accumulator += dt;
        let tick = config.atmosphere.tick_interval_s as f64;
        if tick <= f64::EPSILON {
            return;
        }
        while self.atmos_accumulator >= tick {
            let dt_f32 = tick as f32;
            self.ship.step_atmosphere(dt_f32);
            self.apply_pawn_atmos_effects(dt_f32, &config.atmosphere);
            self.atmos_accumulator -= tick;
        }
    }

    fn process_commands(&mut self, config: &GameConfig) {
        while let Some(command) = self.command_queue.pop_front() {
            match command {
                InteriorCommand::MovePawn { dx, dy } => {
                    self.try_move_pawn(dx, dy);
                }
                InteriorCommand::ToggleSleep => {
                    self.toggle_sleep();
                }
                InteriorCommand::InteractAt { x, y } => {
                    self.interact_at(x, y, &config.atmosphere);
                }
            }
        }
    }

    fn try_move_pawn(&mut self, dx: i32, dy: i32) {
        let target_x = self.pawn.x as i32 + dx;
        let target_y = self.pawn.y as i32 + dy;
        if self.ship.is_passable(target_x, target_y) {
            self.pawn.x = target_x as u32;
            self.pawn.y = target_y as u32;
        }
    }

    fn toggle_sleep(&mut self) {
        let tile = self.ship.tile_type(self.pawn.x, self.pawn.y);
        if tile != TileType::Bed {
            return;
        }
        self.pawn.status = match self.pawn.status {
            PawnStatus::Awake => PawnStatus::Sleeping,
            PawnStatus::Sleeping => PawnStatus::Awake,
        };
    }

    fn interact_at(&mut self, x: u32, y: u32, atmos_cfg: &AtmosphereConfig) {
        if x >= self.ship.width || y >= self.ship.height {
            return;
        }
        let mut door_update: Option<(TileType, Vec<(u32, u32)>)> = None;
        for device in &mut self.ship.devices {
            if !device_contains(device, x, y) {
                continue;
            }
            match &mut device.data {
                DeviceData::BedDevice(_) => {
                    if self.pawn.x == x && self.pawn.y == y {
                        self.toggle_sleep();
                    }
                }
                DeviceData::DoorDevice(data) => {
                    data.open = !data.open;
                    let tile_type = if data.open {
                        TileType::DoorOpen
                    } else {
                        TileType::DoorClosed
                    };
                    let mut tiles = Vec::new();
                    for ty in device.y..device.y + device.h {
                        for tx in device.x..device.x + device.w {
                            tiles.push((tx, ty));
                        }
                    }
                    door_update = Some((tile_type, tiles));
                }
                DeviceData::Light(data) => {
                    data.online = !data.online;
                    device.online = data.online;
                }
                DeviceData::Reactor(data) => {
                    if data.fuel_kg > 0.0 {
                        data.online = !data.online;
                        device.online = data.online;
                    }
                }
                DeviceData::Dispenser(data) => {
                    data.active = !data.active;
                }
                DeviceData::FoodGenerator(data) => {
                    if data.food_units > 0.0 {
                        let consumed = data.food_units.min(1.0);
                        data.food_units -= consumed;
                        self.pawn.needs.hunger = (self.pawn.needs.hunger - 0.2).max(0.0);
                        self.pawn.needs.clamp();
                    }
                }
                _ => {}
            }
            break;
        }
        if let Some((tile_type, tiles)) = door_update {
            for (tx, ty) in tiles {
                self.ship.set_tile_type(tx, ty, tile_type, atmos_cfg);
            }
        }
    }

    fn update_pawn_needs(&mut self, dt: f64) {
        const HUNGER_RATE: f32 = 1.0 / (8.0 * 3600.0);
        const THIRST_RATE: f32 = 1.0 / (4.0 * 3600.0);
        const REST_FATIGUE_RATE: f32 = 1.0 / (16.0 * 3600.0);
        const REST_RECOVER_RATE: f32 = 1.0 / (6.0 * 3600.0);
        let dt_f32 = dt as f32;
        match self.pawn.status {
            PawnStatus::Awake => {
                self.pawn.needs.hunger += HUNGER_RATE * dt_f32;
                self.pawn.needs.thirst += THIRST_RATE * dt_f32;
                self.pawn.needs.rest += REST_FATIGUE_RATE * dt_f32;
            }
            PawnStatus::Sleeping => {
                self.pawn.needs.rest -= REST_RECOVER_RATE * dt_f32;
            }
        }
        self.pawn.needs.clamp();
    }

    fn apply_pawn_atmos_effects(&mut self, dt: f32, atmos_cfg: &AtmosphereConfig) {
        let mut suffocating = false;
        if let Some(cell) = self.ship.tile_atmos_cell_mut(self.pawn.x, self.pawn.y) {
            let required_o2 = O2_CONSUMPTION_KG_PER_SEC * dt;
            let available_o2 = cell.o2_kg;
            let consumed = available_o2.min(required_o2);
            cell.o2_kg -= consumed;
            let production_scale = if required_o2 > 0.0 {
                consumed / required_o2
            } else {
                0.0
            };
            cell.co2_kg += CO2_PRODUCTION_KG_PER_SEC * dt * production_scale;
            if consumed < required_o2 * 0.9 {
                suffocating = true;
            }
            let pressure = cell.pressure_kpa(atmos_cfg);
            let o2_partial = cell.partial_pressure_kpa(GasType::O2, atmos_cfg);
            let co2_partial = cell.partial_pressure_kpa(GasType::CO2, atmos_cfg);
            let mut damage = 0.0;
            if pressure < LOW_PRESSURE_THRESHOLD_KPA {
                damage += (LOW_PRESSURE_THRESHOLD_KPA - pressure) * 0.005 * dt;
            }
            if o2_partial < LOW_O2_PARTIAL_PRESSURE_KPA {
                damage += (LOW_O2_PARTIAL_PRESSURE_KPA - o2_partial) * 0.05 * dt;
            }
            if co2_partial > HIGH_CO2_PARTIAL_PRESSURE_KPA {
                damage += (co2_partial - HIGH_CO2_PARTIAL_PRESSURE_KPA) * 0.05 * dt;
            }
            if damage > 0.0 {
                self.apply_health_damage(damage);
            }
        } else {
            suffocating = true;
            self.apply_health_damage(VACUUM_DAMAGE_PER_SEC * dt);
        }
        if suffocating {
            self.pawn.suffocation_time += dt;
            self.apply_health_damage(SUFFOCATION_DAMAGE_PER_SEC * dt);
        } else {
            self.pawn.suffocation_time = 0.0;
        }
    }

    fn apply_health_damage(&mut self, amount: f32) {
        if amount <= 0.0 {
            return;
        }
        for part in &mut self.pawn.health.body_parts {
            part.hp = (part.hp - amount).max(0.0);
        }
    }
}

#[derive(Clone, Debug)]
pub enum InteriorCommand {
    MovePawn { dx: i32, dy: i32 },
    ToggleSleep,
    InteractAt { x: u32, y: u32 },
}

fn device_contains(device: &Device, x: u32, y: u32) -> bool {
    x >= device.x && y >= device.y && x < device.x + device.w && y < device.y + device.h
}

impl TileType {
    pub fn as_str(&self) -> &'static str {
        match self {
            TileType::Empty => "Empty",
            TileType::Floor => "Floor",
            TileType::Wall => "Wall",
            TileType::Bed => "Bed",
            TileType::DoorClosed => "DoorClosed",
            TileType::DoorOpen => "DoorOpen",
        }
    }
}

impl DeviceType {
    pub fn as_str(&self) -> &'static str {
        match self {
            DeviceType::Tank => "Tank",
            DeviceType::ReactorUranium => "ReactorUranium",
            DeviceType::Dispenser => "Dispenser",
            DeviceType::NavStation => "NavStation",
            DeviceType::Transponder => "Transponder",
            DeviceType::ShipComputer => "ShipComputer",
            DeviceType::BedDevice => "BedDevice",
            DeviceType::Toilet => "Toilet",
            DeviceType::FoodGenerator => "FoodGenerator",
            DeviceType::RCSThruster => "RCSThruster",
            DeviceType::Light => "Light",
            DeviceType::DoorDevice => "DoorDevice",
            DeviceType::PowerLine => "PowerLine",
            DeviceType::GasLine => "GasLine",
        }
    }
}

impl PawnStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            PawnStatus::Awake => "Awake",
            PawnStatus::Sleeping => "Sleeping",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::GameConfig;

    fn make_interior() -> (InteriorWorld, GameConfig) {
        let config = GameConfig::default();
        let interior = InteriorWorld::new_test_ship(&config);
        (interior, config)
    }

    #[test]
    fn hunger_increases_while_awake() {
        let (mut interior, config) = make_interior();
        let initial = interior.pawn.needs.hunger;
        interior.step(3600.0, &config);
        assert!(interior.pawn.needs.hunger > initial);
    }

    #[test]
    fn rest_recovers_while_sleeping() {
        let (mut interior, config) = make_interior();
        interior.pawn.status = PawnStatus::Sleeping;
        interior.pawn.needs.rest = 0.5;
        interior.step(3600.0, &config);
        assert!(interior.pawn.needs.rest < 0.5);
        assert!(interior.pawn.needs.hunger <= 0.0001);
        assert!(interior.pawn.needs.thirst <= 0.0001);
    }

    #[test]
    fn dispenser_moves_gas_from_tank_to_atmos() {
        let (mut interior, config) = make_interior();
        let initial_o2 = interior.ship.total_atmos().o2_kg;
        interior.step(10.0, &config);
        assert!(interior.ship.total_atmos().o2_kg > initial_o2);
    }

    #[test]
    fn atmos_diffusion_conserves_mass() {
        let (mut interior, config) = make_interior();
        for cell in &mut interior.ship.tile_atmos {
            *cell = TileAtmosphere::vacuum(config.atmosphere.baseline_temp_c);
        }
        if let Some(cell) = interior.ship.tile_atmos_cell_mut(5, 3) {
            cell.co2_kg = 1.0;
        }
        let total_before: f32 = interior.ship.tile_atmos.iter().map(|c| c.co2_kg).sum();
        for _ in 0..24 {
            interior
                .ship
                .step_atmosphere(config.atmosphere.tick_interval_s);
        }
        let total_after: f32 = interior.ship.tile_atmos.iter().map(|c| c.co2_kg).sum();
        assert!((total_before - total_after).abs() < 1e-5);
        let spread = interior
            .ship
            .tile_atmos
            .iter()
            .filter(|c| c.co2_kg > 0.0)
            .count();
        assert!(spread > 1);
    }

    #[test]
    fn pawn_breathing_consumes_o2() {
        let (mut interior, config) = make_interior();
        if let Some(device) = interior
            .ship
            .devices
            .iter_mut()
            .find(|d| matches!(d.data, DeviceData::Dispenser(_)))
        {
            if let DeviceData::Dispenser(data) = &mut device.data {
                data.active = false;
            }
        }
        let pawn_x = interior.pawn.x;
        let pawn_y = interior.pawn.y;
        let initial = interior
            .ship
            .tile_atmos_cell(pawn_x, pawn_y)
            .map(|cell| (cell.o2_kg, cell.co2_kg))
            .expect("pawn tile atmos");
        for _ in 0..30 {
            interior.step(config.atmosphere.tick_interval_s as f64, &config);
        }
        let after = interior
            .ship
            .tile_atmos_cell(pawn_x, pawn_y)
            .map(|cell| (cell.o2_kg, cell.co2_kg))
            .expect("pawn tile atmos");
        assert!(after.0 < initial.0);
        assert!(after.1 > initial.1);
    }

    #[test]
    fn pawn_health_initialized_full() {
        let (interior, _) = make_interior();
        assert_eq!(interior.pawn.health.body_parts.len(), 6);
        for part in &interior.pawn.health.body_parts {
            assert!((part.hp - part.max_hp).abs() < f32::EPSILON);
        }
    }

    #[test]
    fn hull_shape_has_vertices() {
        let (interior, _) = make_interior();
        assert!(interior.ship.hull_shape.vertices.len() >= 4);
        assert!(interior.ship.hull_shape.bounding_radius() > 0.0);
    }

    #[test]
    fn interact_with_bed_toggles_sleep() {
        let (mut interior, config) = make_interior();
        interior.pawn.x = 2;
        interior.pawn.y = 2;
        interior.queue_command(InteriorCommand::InteractAt { x: 2, y: 2 });
        interior.step(0.0, &config);
        assert_eq!(interior.pawn.status, PawnStatus::Sleeping);
    }

    #[test]
    fn default_ship_has_one_nav_station() {
        let (interior, _) = make_interior();
        let nav_count = interior
            .ship
            .devices
            .iter()
            .filter(|device| device.device_type == DeviceType::NavStation)
            .count();
        assert_eq!(nav_count, 1);
    }

    #[test]
    fn nav_station_tile_is_reachable() {
        let (interior, _) = make_interior();
        let nav = interior
            .ship
            .devices
            .iter()
            .find(|device| device.device_type == DeviceType::NavStation)
            .expect("nav station");
        let front_y = nav.y + nav.h;
        assert!(front_y < interior.ship.height);
        for x in nav.x..nav.x + nav.w {
            assert!(interior.ship.is_passable(x as i32, front_y as i32));
        }
    }

    #[test]
    fn bed_and_nav_use_two_tiles() {
        let (interior, _) = make_interior();
        let bed = interior
            .ship
            .devices
            .iter()
            .find(|device| device.device_type == DeviceType::BedDevice)
            .expect("bed device");
        assert_eq!((bed.w, bed.h), (2, 1));
        for dx in 0..bed.w {
            assert_eq!(interior.ship.tile_type(bed.x + dx, bed.y), TileType::Bed);
        }
        let nav = interior
            .ship
            .devices
            .iter()
            .find(|device| device.device_type == DeviceType::NavStation)
            .expect("nav station");
        assert_eq!((nav.w, nav.h), (2, 1));
    }

    #[test]
    fn floor_tiles_expose_atmos_samples() {
        let (interior, config) = make_interior();
        assert!(interior
            .ship
            .tile_atmos_sample(1, 1, &config.atmosphere)
            .is_some());
        assert!(interior
            .ship
            .tile_atmos_sample(0, 0, &config.atmosphere)
            .is_none());
    }

    #[test]
    fn standard_air_tile_matches_expected_pressure() {
        let config = GameConfig::default();
        let tile = TileAtmosphere::with_standard_air(&config.atmosphere);
        let pressure = tile.pressure_kpa(&config.atmosphere);
        assert!((pressure - 101.0).abs() < 1.0);
    }

    #[test]
    fn doubling_mass_doubles_pressure() {
        let config = GameConfig::default();
        let mut tile = TileAtmosphere::with_standard_air(&config.atmosphere);
        let base = tile.pressure_kpa(&config.atmosphere);
        tile.o2_kg *= 2.0;
        tile.n2_kg *= 2.0;
        tile.co2_kg *= 2.0;
        let doubled = tile.pressure_kpa(&config.atmosphere);
        assert!((doubled / base - 2.0).abs() < 0.05);
    }
}

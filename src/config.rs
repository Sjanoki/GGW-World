use serde::Deserialize;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[derive(Clone, Debug, Deserialize)]
pub struct GameConfig {
    pub atmosphere: AtmosphereConfig,
    #[serde(default)]
    pub items: HashMap<String, ItemConfig>,
    #[serde(default)]
    pub resources: HashMap<String, ResourceConfig>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct AtmosphereConfig {
    pub tile_size_m: f32,
    pub tile_height_m: f32,
    pub baseline_temp_c: f32,
    pub tick_interval_s: f32,
    pub gases: HashMap<String, GasConfig>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct GasConfig {
    pub display_name: String,
    pub molar_mass_kg_per_mol: f32,
    pub default_mass_kg: f32,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ItemConfig {
    pub display_name: String,
    pub idle_power_kw: f32,
    #[serde(default)]
    pub online_power_kw: Option<f32>,
    #[serde(default)]
    pub capacity_kg: Option<f32>,
    #[serde(default)]
    pub flow_kg_per_s: Option<f32>,
    #[serde(default)]
    pub gas_type: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ResourceConfig {
    pub density_kg_per_m3: f32,
}

impl GameConfig {
    pub fn load() -> Self {
        let path = Path::new("config/game_config.toml");
        match fs::read_to_string(path) {
            Ok(contents) => toml::from_str(&contents).unwrap_or_else(|err| {
                eprintln!(
                    "Failed to parse {} ({}), using defaults.",
                    path.display(),
                    err
                );
                Self::default()
            }),
            Err(err) => {
                eprintln!(
                    "Failed to read {} ({}), using defaults.",
                    path.display(),
                    err
                );
                Self::default()
            }
        }
    }
}

impl Default for GameConfig {
    fn default() -> Self {
        let mut gases = HashMap::new();
        gases.insert(
            "O2".to_string(),
            GasConfig {
                display_name: "Oxygen".to_string(),
                molar_mass_kg_per_mol: 0.031_998,
                default_mass_kg: 0.5585,
            },
        );
        gases.insert(
            "N2".to_string(),
            GasConfig {
                display_name: "Nitrogen".to_string(),
                molar_mass_kg_per_mol: 0.028_013_4,
                default_mass_kg: 1.8393,
            },
        );
        gases.insert(
            "CO2".to_string(),
            GasConfig {
                display_name: "Carbon Dioxide".to_string(),
                molar_mass_kg_per_mol: 0.04401,
                default_mass_kg: 0.0015,
            },
        );

        let mut items = HashMap::new();
        items.insert(
            "reactor_uranium".to_string(),
            ItemConfig {
                display_name: "Reactor (Uranium)".to_string(),
                idle_power_kw: 0.0,
                online_power_kw: Some(-500.0),
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "nav_station".to_string(),
            ItemConfig {
                display_name: "NavStation".to_string(),
                idle_power_kw: 1.5,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "ship_computer".to_string(),
            ItemConfig {
                display_name: "ShipComputer".to_string(),
                idle_power_kw: 2.5,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "transponder".to_string(),
            ItemConfig {
                display_name: "Transponder".to_string(),
                idle_power_kw: 5.0,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "food_generator".to_string(),
            ItemConfig {
                display_name: "FoodGenerator".to_string(),
                idle_power_kw: 2.0,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "tank".to_string(),
            ItemConfig {
                display_name: "Tank".to_string(),
                idle_power_kw: 0.25,
                online_power_kw: None,
                capacity_kg: Some(100.0),
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "dispenser".to_string(),
            ItemConfig {
                display_name: "Dispenser".to_string(),
                idle_power_kw: 0.25,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: Some(0.02),
                gas_type: Some("O2".to_string()),
            },
        );
        items.insert(
            "light".to_string(),
            ItemConfig {
                display_name: "Light".to_string(),
                idle_power_kw: 0.1,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "bed".to_string(),
            ItemConfig {
                display_name: "BedDevice".to_string(),
                idle_power_kw: 0.0,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );
        items.insert(
            "door".to_string(),
            ItemConfig {
                display_name: "Door".to_string(),
                idle_power_kw: 0.0,
                online_power_kw: None,
                capacity_kg: None,
                flow_kg_per_s: None,
                gas_type: None,
            },
        );

        let mut resources = HashMap::new();
        resources.insert(
            "iron_ore".to_string(),
            ResourceConfig {
                density_kg_per_m3: 5200.0,
            },
        );
        resources.insert(
            "gold_ore".to_string(),
            ResourceConfig {
                density_kg_per_m3: 19_300.0,
            },
        );
        resources.insert(
            "silver_ore".to_string(),
            ResourceConfig {
                density_kg_per_m3: 10_490.0,
            },
        );

        Self {
            atmosphere: AtmosphereConfig {
                tile_size_m: 1.0,
                tile_height_m: 2.0,
                baseline_temp_c: 20.0,
                tick_interval_s: 0.25,
                gases,
            },
            items,
            resources,
        }
    }
}

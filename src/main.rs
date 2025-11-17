use std::env;
use std::f64::consts::FRAC_PI_4;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use ggw_world::{
    interior::{DeviceData, GasType, InteriorCommand, InteriorWorld},
    BodyState, BodyType, HullShape, OrbitState, Vec2, World, DESPAWN_RADIUS_M,
    GRAVITY_WELL_RADIUS_M, PLANET_RADIUS_M, TILE_SIZE_METERS,
};

const MU_EARTH: f64 = 3.986_004_418e14;
const DEFAULT_TIME_SCALE: f64 = 1.0;
const MAX_TIME_SCALE: f64 = 10_000.0;
const MAX_SIM_DT: f64 = 1.0;
const SNAPSHOT_SLEEP_MS: u64 = 50;
const SERVER_ADDR: &str = "127.0.0.1:40000";
fn main() {
    let args: Vec<String> = env::args().collect();
    if args.iter().any(|arg| arg == "--stdio") {
        run_stdio_mode();
    } else {
        run_tcp_server();
    }
}

fn run_stdio_mode() {
    let mut world = build_initial_world();
    let stdin_thread = spawn_command_listener();
    let stdout = io::stdout();
    let mut handle = stdout.lock();
    let mut time_scale = DEFAULT_TIME_SCALE;
    let mut last_real = Instant::now();

    loop {
        for command in stdin_thread.drain_commands() {
            apply_command(&mut world, command, &mut time_scale);
        }

        let snapshot_json = tick_world(&mut world, time_scale, &mut last_real);
        writeln!(handle, "{}", snapshot_json).expect("stdout write");
        handle.flush().expect("stdout flush");
        thread::sleep(Duration::from_millis(SNAPSHOT_SLEEP_MS));
    }
}

fn run_tcp_server() {
    let listener = TcpListener::bind(SERVER_ADDR).expect("failed to bind TCP listener");
    println!("GGW server listening on {}", SERVER_ADDR);

    let mut world = build_initial_world();
    let (cmd_tx, cmd_rx) = mpsc::channel::<Command>();
    let (new_client_tx, new_client_rx) = mpsc::channel::<mpsc::Sender<String>>();

    let accept_cmd_tx = cmd_tx.clone();
    thread::spawn(move || accept_clients(listener, accept_cmd_tx, new_client_tx));

    let mut clients: Vec<mpsc::Sender<String>> = Vec::new();
    let mut time_scale = DEFAULT_TIME_SCALE;
    let mut last_real = Instant::now();

    loop {
        while let Ok(new_client) = new_client_rx.try_recv() {
            clients.push(new_client);
        }

        while let Ok(command) = cmd_rx.try_recv() {
            apply_command(&mut world, command, &mut time_scale);
        }

        let snapshot_json = tick_world(&mut world, time_scale, &mut last_real);
        clients.retain(|sender| sender.send(snapshot_json.clone()).is_ok());
        thread::sleep(Duration::from_millis(SNAPSHOT_SLEEP_MS));
    }
}

fn accept_clients(
    listener: TcpListener,
    cmd_tx: mpsc::Sender<Command>,
    new_client_tx: mpsc::Sender<mpsc::Sender<String>>,
) {
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let sender = spawn_client_connection(stream, cmd_tx.clone());
                if new_client_tx.send(sender).is_err() {
                    break;
                }
            }
            Err(err) => {
                eprintln!("Failed to accept client: {}", err);
            }
        }
    }
}

fn spawn_client_connection(
    stream: TcpStream,
    cmd_tx: mpsc::Sender<Command>,
) -> mpsc::Sender<String> {
    let (snapshot_tx, snapshot_rx) = mpsc::channel::<String>();

    let reader_stream = stream
        .try_clone()
        .expect("failed to clone stream for reader");
    let reader_cmd_tx = cmd_tx.clone();
    thread::spawn(move || {
        let reader = BufReader::new(reader_stream);
        for line in reader.lines() {
            match line {
                Ok(line) => {
                    if let Some(command) = parse_command(&line) {
                        if reader_cmd_tx.send(command).is_err() {
                            break;
                        }
                    }
                }
                Err(_) => break,
            }
        }
    });

    thread::spawn(move || {
        let mut writer = BufWriter::new(stream);
        while let Ok(snapshot) = snapshot_rx.recv() {
            if writeln!(writer, "{}", snapshot).is_err() {
                break;
            }
            if writer.flush().is_err() {
                break;
            }
        }
    });

    snapshot_tx
}

fn build_initial_world() -> World {
    let mut world = World::new(MU_EARTH);
    let r_planet = PLANET_RADIUS_M;

    let ship_orbit = OrbitState {
        semi_major_axis: r_planet + 1_000_000.0,
        eccentricity: 0.0,
        arg_of_periapsis: 0.0,
        mean_anomaly_at_epoch: 0.0,
        epoch: 0.0,
    };

    let asteroid_orbit = OrbitState {
        semi_major_axis: r_planet + 3_000_000.0,
        eccentricity: 0.0,
        arg_of_periapsis: 0.0,
        mean_anomaly_at_epoch: 0.0,
        epoch: 0.0,
    };

    let perigee = r_planet + 1_000_000.0;
    let apogee = r_planet + 5_000_000.0;
    let debris_semi_major = 0.5 * (perigee + apogee);
    let debris_eccentricity = (apogee - perigee) / (apogee + perigee);
    let debris_orbit = OrbitState {
        semi_major_axis: debris_semi_major,
        eccentricity: debris_eccentricity,
        arg_of_periapsis: FRAC_PI_4,
        mean_anomaly_at_epoch: 0.0,
        epoch: 0.0,
    };

    let ship_hull = world.interior.ship.hull_shape.clone();
    world.add_body(sample_body(
        1,
        BodyType::Ship,
        ship_orbit,
        20.0,
        Some(ship_hull),
    ));
    world.add_body(sample_body(
        2,
        BodyType::Asteroid,
        asteroid_orbit,
        1_000.0,
        None,
    ));
    world.add_body(sample_body(3, BodyType::Debris, debris_orbit, 10.0, None));

    world.step(0.0);
    world
}

fn tick_world(world: &mut World, time_scale: f64, last_real: &mut Instant) -> String {
    let now = Instant::now();
    let real_dt = now.duration_since(*last_real).as_secs_f64();
    *last_real = now;

    let mut sim_dt = time_scale * real_dt;
    if sim_dt > MAX_SIM_DT {
        sim_dt = MAX_SIM_DT;
    }
    if sim_dt < 0.0 {
        sim_dt = 0.0;
    }

    world.step(sim_dt);
    build_snapshot_json(world)
}

fn apply_command(world: &mut World, command: Command, time_scale: &mut f64) {
    match command {
        Command::SetTimeScale(scale) => {
            *time_scale = scale;
        }
        Command::MovePawn { dx, dy } => {
            world
                .interior
                .queue_command(InteriorCommand::MovePawn { dx, dy });
        }
        Command::ToggleSleep => {
            world.interior.queue_command(InteriorCommand::ToggleSleep);
        }
        Command::InteractAt { x, y } => {
            world
                .interior
                .queue_command(InteriorCommand::InteractAt { x, y });
        }
    }
}

struct CommandListener {
    receiver: mpsc::Receiver<String>,
}

impl CommandListener {
    fn drain_commands(&self) -> Vec<Command> {
        use std::sync::mpsc::TryRecvError;
        let mut commands = Vec::new();
        loop {
            match self.receiver.try_recv() {
                Ok(line) => {
                    if let Some(command) = parse_command(&line) {
                        commands.push(command);
                    }
                }
                Err(TryRecvError::Empty) => return commands,
                Err(TryRecvError::Disconnected) => return commands,
            }
        }
    }
}

fn spawn_command_listener() -> CommandListener {
    let (tx, rx) = mpsc::channel::<String>();
    thread::spawn(move || {
        let stdin = io::stdin();
        for line in stdin.lock().lines() {
            match line {
                Ok(line) => {
                    if tx.send(line).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });
    CommandListener { receiver: rx }
}

fn sample_body(
    id: u64,
    body_type: BodyType,
    orbit: OrbitState,
    radius: f64,
    hull_shape: Option<HullShape>,
) -> BodyState {
    let adjusted_radius = hull_shape
        .as_ref()
        .map(|shape| shape.bounding_radius())
        .unwrap_or(radius);
    BodyState {
        id,
        mass: 1_000.0,
        radius: adjusted_radius,
        orbit,
        position: Vec2::zero(),
        velocity: Vec2::zero(),
        body_type,
        hull_shape,
    }
}

fn build_snapshot_json(world: &World) -> String {
    let mut json = format!(
        "{{\"sim_time\":{},\"planet_radius_m\":{},\"gravity_well_radius_m\":{},\"despawn_radius_m\":{},\"mu\":{},\"bodies\":[",
        world.sim_time,
        world.planet_radius,
        GRAVITY_WELL_RADIUS_M,
        DESPAWN_RADIUS_M,
        world.mu
    );
    for (index, body) in world.bodies.iter().enumerate() {
        if index > 0 {
            json.push(',');
        }
        json.push('{');
        json.push_str(&format!(
            "\"id\":{},\"body_type\":\"{}\",\"radius_m\":{},\"x\":{},\"y\":{},\"vx\":{},\"vy\":{}",
            body.id,
            body_type_name(body.body_type),
            body.radius,
            body.position.x,
            body.position.y,
            body.velocity.x,
            body.velocity.y
        ));
        if let Some(hull) = &body.hull_shape {
            json.push_str(",\"hull_shape\":{");
            json.push_str(&format!("\"tile_size_m\":{}", TILE_SIZE_METERS));
            json.push_str(",\"vertices\":[");
            for (idx, vertex) in hull.vertices.iter().enumerate() {
                if idx > 0 {
                    json.push(',');
                }
                json.push_str(&format!("{{\"x\":{},\"y\":{}}}", vertex.x, vertex.y));
            }
            json.push_str("]}");
        }
        json.push('}');
    }
    json.push_str("]");
    json.push(',');
    json.push_str(&build_interior_json(&world.interior));
    json.push('}');
    json
}

fn build_interior_json(interior: &InteriorWorld) -> String {
    let ship = &interior.ship;
    let mut json = String::new();
    json.push_str("\"interior\":{");
    json.push_str(&format!(
        "\"width\":{},\"height\":{},",
        ship.width, ship.height
    ));
    json.push_str("\"tiles\":[");
    for y in 0..ship.height {
        if y > 0 {
            json.push(',');
        }
        json.push('[');
        for x in 0..ship.width {
            if x > 0 {
                json.push(',');
            }
            let tile_type = ship.tile_type(x, y);
            json.push('{');
            json.push_str(&format!("\"type\":\"{}\"", tile_type.as_str()));
            if let Some(sample) = ship.tile_atmos_sample(x, y) {
                json.push_str(&format!(
                    ",\"atmos\":{{\"pressure_kpa\":{},\"o2_fraction\":{},\"n2_fraction\":{},\"co2_fraction\":{}}}",
                    sample.pressure_kpa, sample.o2_fraction, sample.n2_fraction, sample.co2_fraction
                ));
            } else {
                json.push_str(",\"atmos\":null");
            }
            json.push('}');
        }
        json.push(']');
    }
    json.push_str("],");
    json.push_str("\"devices\":[");
    for (index, device) in ship.devices.iter().enumerate() {
        if index > 0 {
            json.push(',');
        }
        json.push('{');
        json.push_str(&format!(
            "\"id\":{},\"kind\":\"{}\",\"x\":{},\"y\":{},\"w\":{},\"h\":{},\"online\":{},\"power_kw\":{}",
            device.id,
            device.device_type.as_str(),
            device.x,
            device.y,
            device.w,
            device.h,
            if device.online { "true" } else { "false" },
            device.power_kw
        ));
        match &device.data {
            DeviceData::Reactor(data) => {
                json.push_str(&format!(
                    ",\"fuel_kg\":{},\"max_fuel_kg\":{},\"power_output_kw\":{},\"fuel_burn_rate_kg_per_s\":{},\"reactor_online\":{}",
                    data.fuel_kg,
                    data.max_fuel_kg,
                    data.power_output_kw,
                    data.fuel_burn_rate_kg_per_s,
                    if data.online { "true" } else { "false" }
                ));
            }
            DeviceData::Tank(data) => {
                json.push_str(&format!(
                    ",\"o2_kg\":{},\"n2_kg\":{},\"co2_kg\":{},\"xenon_kg\":{},\"capacity_kg\":{}",
                    data.o2_kg, data.n2_kg, data.co2_kg, data.xenon_kg, data.capacity_kg
                ));
            }
            DeviceData::Dispenser(data) => {
                json.push_str(&format!(
                    ",\"active\":{},\"rate_kg_per_s\":{},\"gas_type\":\"{}\",\"connected_tank_id\":{}",
                    if data.active { "true" } else { "false" },
                    data.rate_kg_per_s,
                    gas_type_name(data.gas_type),
                    data
                        .connected_tank_id
                        .map(|id| id.to_string())
                        .unwrap_or_else(|| "null".to_string())
                ));
            }
            DeviceData::Light(data) => {
                json.push_str(&format!(
                    ",\"intensity\":{},\"light_online\":{}",
                    data.intensity,
                    if data.online { "true" } else { "false" }
                ));
            }
            DeviceData::NavStation(data) => {
                json.push_str(&format!(
                    ",\"nav_online\":{}",
                    if data.online { "true" } else { "false" }
                ));
            }
            DeviceData::Transponder(data) => {
                json.push_str(&format!(
                    ",\"callsign\":\"{}\",\"transponder_online\":{}",
                    data.callsign,
                    if data.online { "true" } else { "false" }
                ));
            }
            DeviceData::ShipComputer(data) => {
                json.push_str(&format!(
                    ",\"ship_computer_online\":{}",
                    if data.online { "true" } else { "false" }
                ));
            }
            DeviceData::DoorDevice(data) => {
                json.push_str(&format!(
                    ",\"open\":{}",
                    if data.open { "true" } else { "false" }
                ));
            }
            DeviceData::FoodGenerator(data) => {
                json.push_str(&format!(
                    ",\"food_units\":{},\"max_food_units\":{},\"food_online\":{}",
                    data.food_units,
                    data.max_food_units,
                    if data.online { "true" } else { "false" }
                ));
            }
            DeviceData::BedDevice(_)
            | DeviceData::Toilet(_)
            | DeviceData::RCSThruster(_)
            | DeviceData::PowerLine(_)
            | DeviceData::GasLine(_) => {}
        }
        json.push('}');
    }
    json.push_str("],");
    json.push_str(&format!(
        "\"atmos\":{{\"o2_kg\":{},\"n2_kg\":{},\"co2_kg\":{}}},",
        ship.atmos.o2_kg, ship.atmos.n2_kg, ship.atmos.co2_kg
    ));
    json.push_str(&format!(
        "\"power\":{{\"net_kw\":{},\"total_production_kw\":{},\"total_consumption_kw\":{}}},",
        ship.power.net_kw, ship.power.total_production_kw, ship.power.total_consumption_kw
    ));
    let pawn = &interior.pawn;
    json.push_str("\"pawn\":{");
    json.push_str(&format!(
        "\"x\":{},\"y\":{},\"status\":\"{}\"",
        pawn.x,
        pawn.y,
        pawn.status.as_str()
    ));
    json.push_str(&format!(
        ",\"needs\":{{\"hunger\":{},\"thirst\":{},\"rest\":{}}}",
        pawn.needs.hunger, pawn.needs.thirst, pawn.needs.rest
    ));
    json.push_str(",\"health\":{\"body_parts\":[");
    for (idx, part) in pawn.health.body_parts.iter().enumerate() {
        if idx > 0 {
            json.push(',');
        }
        json.push_str(&format!(
            "{{\"name\":\"{}\",\"hp\":{},\"max_hp\":{},\"vital\":{}}}",
            part.name,
            part.hp,
            part.max_hp,
            if part.vital { "true" } else { "false" }
        ));
    }
    json.push_str("]}");
    json.push('}');
    json.push('}');
    json
}

fn body_type_name(body_type: BodyType) -> &'static str {
    match body_type {
        BodyType::Ship => "Ship",
        BodyType::Asteroid => "Asteroid",
        BodyType::Debris => "Debris",
        BodyType::Missile => "Missile",
    }
}

fn gas_type_name(gas: GasType) -> &'static str {
    match gas {
        GasType::O2 => "O2",
        GasType::N2 => "N2",
        GasType::CO2 => "CO2",
        GasType::Xenon => "Xenon",
    }
}

fn parse_command(line: &str) -> Option<Command> {
    let trimmed = line.trim();
    if !trimmed.starts_with('{') {
        return None;
    }
    if trimmed.contains("set_time_scale") {
        return parse_time_scale_command(trimmed).map(Command::SetTimeScale);
    }
    if trimmed.contains("move_pawn") {
        let dx = extract_number::<i32>(trimmed, "\"dx\"")?;
        let dy = extract_number::<i32>(trimmed, "\"dy\"")?;
        return Some(Command::MovePawn { dx, dy });
    }
    if trimmed.contains("toggle_sleep") {
        return Some(Command::ToggleSleep);
    }
    if trimmed.contains("interact_at") {
        let x = extract_number::<u32>(trimmed, "\"x\"")?;
        let y = extract_number::<u32>(trimmed, "\"y\"")?;
        return Some(Command::InteractAt { x, y });
    }
    None
}

fn parse_time_scale_command(line: &str) -> Option<f64> {
    extract_number::<f64>(line, "\"time_scale\"").map(clamp_time_scale)
}

fn clamp_time_scale(value: f64) -> f64 {
    if value.is_nan() {
        DEFAULT_TIME_SCALE
    } else {
        value.max(0.0).min(MAX_TIME_SCALE)
    }
}

fn extract_number<T: core::str::FromStr>(line: &str, key: &str) -> Option<T> {
    let start = line.find(key)? + key.len();
    let after_key = line.get(start..)?;
    let colon_index = after_key.find(':')?;
    let after_colon = after_key.get(colon_index + 1..)?.trim_start();
    let end_index = after_colon
        .find(|c: char| c == ',' || c == '}')
        .unwrap_or(after_colon.len());
    let value_str = after_colon[..end_index].trim();
    value_str.parse::<T>().ok()
}

enum Command {
    SetTimeScale(f64),
    MovePawn { dx: i32, dy: i32 },
    ToggleSleep,
    InteractAt { x: u32, y: u32 },
}

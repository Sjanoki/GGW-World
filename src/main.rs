use std::f64::consts::FRAC_PI_4;
use std::io::{self, BufRead, Write};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use ggw_world::{
    interior::{InteriorCommand, InteriorWorld},
    BodyState, BodyType, OrbitState, Vec2, World, DESPAWN_RADIUS_M, GRAVITY_WELL_RADIUS_M,
    PLANET_RADIUS_M,
};

const MU_EARTH: f64 = 3.986_004_418e14;
const DEFAULT_DT_SECONDS: f64 = 10.0;
const MAX_TIME_SCALE: f64 = 10_000.0;
const MAX_SIM_DT: f64 = 1.0;
const SNAPSHOT_SLEEP_MS: u64 = 50;

fn main() {
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

    world.add_body(sample_body(1, BodyType::Ship, ship_orbit, 20.0));
    world.add_body(sample_body(2, BodyType::Asteroid, asteroid_orbit, 1_000.0));
    world.add_body(sample_body(3, BodyType::Debris, debris_orbit, 10.0));

    // Prime cached position/velocity fields.
    world.step(0.0);

    let stdin_thread = spawn_command_listener();
    let stdout = io::stdout();
    let mut handle = stdout.lock();
    let mut time_scale = DEFAULT_DT_SECONDS;
    let mut last_real = Instant::now();

    loop {
        for command in stdin_thread.drain_commands() {
            match command {
                Command::SetTimeScale(scale) => {
                    time_scale = scale;
                }
                Command::MovePawn { dx, dy } => {
                    world
                        .interior
                        .queue_command(InteriorCommand::MovePawn { dx, dy });
                }
                Command::ToggleSleep => {
                    world.interior.queue_command(InteriorCommand::ToggleSleep);
                }
            }
        }

        let now = Instant::now();
        let real_dt = now.duration_since(last_real).as_secs_f64();
        last_real = now;

        let mut sim_dt = time_scale * real_dt;
        if sim_dt > MAX_SIM_DT {
            sim_dt = MAX_SIM_DT;
        }
        if sim_dt < 0.0 {
            sim_dt = 0.0;
        }

        world.step(sim_dt);
        let snapshot_json = build_snapshot_json(&world);
        writeln!(handle, "{}", snapshot_json).expect("stdout write");
        handle.flush().expect("stdout flush");
        thread::sleep(Duration::from_millis(SNAPSHOT_SLEEP_MS));
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

fn sample_body(id: u64, body_type: BodyType, orbit: OrbitState, radius: f64) -> BodyState {
    BodyState {
        id,
        mass: 1_000.0,
        radius,
        orbit,
        position: Vec2::zero(),
        velocity: Vec2::zero(),
        body_type,
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
        json.push_str(&format!(
            "{{\"id\":{},\"body_type\":\"{}\",\"radius_m\":{},\"x\":{},\"y\":{},\"vx\":{},\"vy\":{}}}",
            body.id,
            body_type_name(body.body_type),
            body.radius,
            body.position.x,
            body.position.y,
            body.velocity.x,
            body.velocity.y
        ));
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
            let tile_name = ship.tile_type(x, y).as_str();
            json.push_str(&format!("\"{}\"", tile_name));
        }
        json.push(']');
    }
    json.push_str("],");
    json.push_str("\"devices\":[");
    for (index, device) in ship.devices.iter().enumerate() {
        if index > 0 {
            json.push(',');
        }
        json.push_str(&format!(
            "{{\"id\":{},\"kind\":\"{}\",\"x\":{},\"y\":{},\"w\":{},\"h\":{}}}",
            device.id,
            device.device_type.as_str(),
            device.x,
            device.y,
            device.w,
            device.h
        ));
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
    None
}

fn parse_time_scale_command(line: &str) -> Option<f64> {
    extract_number::<f64>(line, "\"time_scale\"").map(clamp_time_scale)
}

fn clamp_time_scale(value: f64) -> f64 {
    if value.is_nan() {
        DEFAULT_DT_SECONDS
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
}

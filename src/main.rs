use std::f64::consts::FRAC_PI_4;
use std::io::{self, BufRead, Write};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use ggw_world::{
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
        if let Some(new_scale) = stdin_thread.try_recv_time_scale() {
            time_scale = new_scale;
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
    fn try_recv_time_scale(&self) -> Option<f64> {
        use std::sync::mpsc::TryRecvError;
        let mut latest: Option<f64> = None;
        loop {
            match self.receiver.try_recv() {
                Ok(line) => {
                    if let Some(scale) = parse_time_scale_command(&line) {
                        latest = Some(scale);
                    }
                }
                Err(TryRecvError::Empty) => return latest,
                Err(TryRecvError::Disconnected) => return latest,
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
    json.push_str("]}");
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

fn parse_time_scale_command(line: &str) -> Option<f64> {
    let trimmed = line.trim();
    if !trimmed.starts_with('{') || !trimmed.contains("set_time_scale") {
        return None;
    }
    let key = "\"time_scale\"";
    let start = trimmed.find(key)? + key.len();
    let after_key = trimmed.get(start..)?;
    let colon_index = after_key.find(':')?;
    let after_colon = after_key.get(colon_index + 1..)?.trim_start();
    let end_index = after_colon
        .find(|c: char| c == ',' || c == '}')
        .unwrap_or(after_colon.len());
    let value_str = after_colon[..end_index].trim();
    value_str
        .parse::<f64>()
        .ok()
        .map(|value| clamp_time_scale(value))
}

fn clamp_time_scale(value: f64) -> f64 {
    if value.is_nan() {
        DEFAULT_DT_SECONDS
    } else {
        value.max(0.0).min(MAX_TIME_SCALE)
    }
}

use std::io::{self, Write};
use std::thread;
use std::time::Duration;

use ggw_world::{BodyState, BodyType, OrbitState, Vec2, World};

const MU_EARTH: f64 = 3.986_004_418e14;
const DT_SECONDS: f64 = 10.0;
const SNAPSHOT_SLEEP_MS: u64 = 50;

fn main() {
    let mut world = World::new(MU_EARTH);

    let ship_orbit = OrbitState {
        semi_major_axis: 7_000_000.0,
        eccentricity: 0.0,
        arg_of_periapsis: 0.0,
        mean_anomaly_at_epoch: 0.0,
        epoch: 0.0,
    };

    let asteroid_orbit = OrbitState {
        semi_major_axis: 10_000_000.0,
        eccentricity: 0.0,
        arg_of_periapsis: 0.0,
        mean_anomaly_at_epoch: 0.0,
        epoch: 0.0,
    };

    let debris_orbit = OrbitState {
        semi_major_axis: 8_000_000.0,
        eccentricity: 0.3,
        arg_of_periapsis: 0.8,
        mean_anomaly_at_epoch: 1.0,
        epoch: 0.0,
    };

    world.add_body(sample_body(1, BodyType::Ship, ship_orbit));
    world.add_body(sample_body(2, BodyType::Asteroid, asteroid_orbit));
    world.add_body(sample_body(3, BodyType::Debris, debris_orbit));

    // Prime cached position/velocity fields.
    world.step(0.0);

    let stdout = io::stdout();
    let mut handle = stdout.lock();

    loop {
        world.step(DT_SECONDS);
        let snapshot_json = build_snapshot_json(&world);
        writeln!(handle, "{}", snapshot_json).expect("stdout write");
        handle.flush().expect("stdout flush");
        thread::sleep(Duration::from_millis(SNAPSHOT_SLEEP_MS));
    }
}

fn sample_body(id: u64, body_type: BodyType, orbit: OrbitState) -> BodyState {
    BodyState {
        id,
        mass: 1_000.0,
        radius: 5.0,
        orbit,
        position: Vec2::zero(),
        velocity: Vec2::zero(),
        body_type,
    }
}

fn build_snapshot_json(world: &World) -> String {
    let mut json = format!("{{\"sim_time\":{},\"bodies\":[", world.sim_time);
    for (index, body) in world.bodies.iter().enumerate() {
        if index > 0 {
            json.push(',');
        }
        json.push_str(&format!(
            "{{\"id\":{},\"body_type\":\"{}\",\"x\":{},\"y\":{},\"vx\":{},\"vy\":{}}}",
            body.id,
            body_type_name(body.body_type),
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

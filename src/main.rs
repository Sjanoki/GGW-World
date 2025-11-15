use std::f64::consts::FRAC_PI_4;
use std::io::{self, Write};
use std::thread;
use std::time::Duration;

use ggw_world::{
    BodyState, BodyType, OrbitState, Vec2, World, DESPAWN_RADIUS_M, GRAVITY_WELL_RADIUS_M,
    PLANET_RADIUS_M,
};

const MU_EARTH: f64 = 3.986_004_418e14;
const DT_SECONDS: f64 = 10.0;
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

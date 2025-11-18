use core::f64::consts::PI;

pub mod config;

pub mod interior;

use config::GameConfig;
use interior::InteriorWorld;

pub const PLANET_RADIUS_M: f64 = 6_371_000.0;
pub const GRAVITY_WELL_RADIUS_M: f64 = 1_500_000_000.0;
pub const GRAVITY_WELL_ALTITUDE_M: f64 = GRAVITY_WELL_RADIUS_M - PLANET_RADIUS_M;
pub const DESPAWN_RADIUS_M: f64 = PLANET_RADIUS_M + 3.0 * GRAVITY_WELL_ALTITUDE_M;
pub const TILE_SIZE_METERS: f64 = 1.0;

#[derive(Clone, Debug)]
pub struct HullShape {
    pub vertices: Vec<Vec2>,
}

impl HullShape {
    pub fn bounding_radius(&self) -> f64 {
        self.vertices
            .iter()
            .map(|v| v.length())
            .fold(0.0_f64, f64::max)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Vec2 {
    pub x: f64,
    pub y: f64,
}

impl Vec2 {
    pub fn zero() -> Self {
        Self { x: 0.0, y: 0.0 }
    }

    pub fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }

    pub fn length_squared(self) -> f64 {
        self.x * self.x + self.y * self.y
    }

    pub fn length(self) -> f64 {
        self.length_squared().sqrt()
    }

    pub fn normalized(self) -> Self {
        let len = self.length();
        if len <= 1e-12 {
            Self::zero()
        } else {
            self.scale(1.0 / len)
        }
    }

    pub fn add(self, other: Self) -> Self {
        Self {
            x: self.x + other.x,
            y: self.y + other.y,
        }
    }

    pub fn sub(self, other: Self) -> Self {
        Self {
            x: self.x - other.x,
            y: self.y - other.y,
        }
    }

    pub fn scale(self, k: f64) -> Self {
        Self {
            x: self.x * k,
            y: self.y * k,
        }
    }

    pub fn dot(self, other: Self) -> f64 {
        self.x * other.x + self.y * other.y
    }
}

impl core::ops::Add for Vec2 {
    type Output = Vec2;

    fn add(self, rhs: Self) -> Self::Output {
        self.add(rhs)
    }
}

impl core::ops::Sub for Vec2 {
    type Output = Vec2;

    fn sub(self, rhs: Self) -> Self::Output {
        self.sub(rhs)
    }
}

impl core::ops::Mul<f64> for Vec2 {
    type Output = Vec2;

    fn mul(self, rhs: f64) -> Self::Output {
        self.scale(rhs)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct OrbitState {
    pub semi_major_axis: f64,
    pub eccentricity: f64,
    pub arg_of_periapsis: f64,
    pub mean_anomaly_at_epoch: f64,
    pub epoch: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BodyType {
    Ship,
    Asteroid,
    Debris,
    Missile,
}

#[derive(Clone, Debug)]
pub struct BodyState {
    pub id: u64,
    pub mass: f64,
    pub radius: f64,
    pub orbit: OrbitState,
    pub position: Vec2,
    pub velocity: Vec2,
    pub body_type: BodyType,
    pub hull_shape: Option<HullShape>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ThrustType {
    Rcs,
    Chemical,
    Ion,
}

#[derive(Clone, Debug)]
pub struct ThrustEvent {
    pub body_id: u64,
    pub time: f64,
    pub delta_v: Vec2,
    pub thrust_type: ThrustType,
}

#[derive(Clone, Debug)]
pub struct CollisionEvent {
    pub time: f64,
    pub body_a: u64,
    pub body_b: u64,
    pub relative_velocity: Vec2,
    pub contact_point: Vec2,
}

fn normalize_angle(mut angle: f64) -> f64 {
    while angle <= -PI {
        angle += 2.0 * PI;
    }
    while angle > PI {
        angle -= 2.0 * PI;
    }
    angle
}

fn clamp(value: f64, min: f64, max: f64) -> f64 {
    if value < min {
        min
    } else if value > max {
        max
    } else {
        value
    }
}

/// Convert an OrbitState into Cartesian position/velocity at time `t`.
pub fn orbit_to_cartesian(orbit: &OrbitState, mu: f64, t: f64) -> (Vec2, Vec2) {
    assert!(
        orbit.semi_major_axis > 0.0,
        "semi-major axis must be positive"
    );
    assert!(
        orbit.eccentricity >= 0.0 && orbit.eccentricity < 1.0,
        "eccentricity out of range"
    );

    let a = orbit.semi_major_axis;
    let e = orbit.eccentricity;
    let n = (mu / (a * a * a)).sqrt();
    let dt = t - orbit.epoch;
    let mut m = orbit.mean_anomaly_at_epoch + n * dt;
    m = normalize_angle(m);

    let mut e_anom = if e < 0.8 { m } else { PI };
    for _ in 0..32 {
        let f = e_anom - e * e_anom.sin() - m;
        let f_prime = 1.0 - e * e_anom.cos();
        if f_prime.abs() < 1e-12 {
            break;
        }
        let delta = f / f_prime;
        e_anom -= delta;
        if delta.abs() < 1e-12 {
            break;
        }
    }

    let cos_e = e_anom.cos();
    let sin_e = e_anom.sin();
    let factor = 1.0 - e * cos_e;
    let sqrt_one_minus_e2 = (1.0 - e * e).max(0.0).sqrt();

    let x_orb = a * (cos_e - e);
    let y_orb = a * sqrt_one_minus_e2 * sin_e;

    let vx_orb = -a * sin_e * n / factor;
    let vy_orb = a * sqrt_one_minus_e2 * cos_e * n / factor;

    let cos_w = orbit.arg_of_periapsis.cos();
    let sin_w = orbit.arg_of_periapsis.sin();

    let position = Vec2::new(cos_w * x_orb - sin_w * y_orb, sin_w * x_orb + cos_w * y_orb);
    let velocity = Vec2::new(
        cos_w * vx_orb - sin_w * vy_orb,
        sin_w * vx_orb + cos_w * vy_orb,
    );

    (position, velocity)
}

/// Convert Cartesian state to OrbitState at epoch `t`.
pub fn cartesian_to_orbit(position: Vec2, velocity: Vec2, mu: f64, t: f64) -> OrbitState {
    let r = position.length();
    let v = velocity.length();
    let h = position.x * velocity.y - position.y * velocity.x;
    assert!(h.abs() > 0.0, "degenerate orbit (zero angular momentum)");

    let energy = 0.5 * v * v - mu / r;
    let a = -mu / (2.0 * energy);
    assert!(a.is_finite() && a > 0.0, "invalid semi-major axis");

    let v_sq = v * v;
    let r_vec = position;
    let v_vec = velocity;
    let v_radial = if r > 0.0 { r_vec.dot(v_vec) / r } else { 0.0 };
    let term1 = v_sq - mu / r;
    let e_vec = r_vec
        .scale(term1)
        .sub(v_vec.scale(v_radial).scale(r))
        .scale(1.0 / mu);
    let mut e = e_vec.length();
    if e < 1e-12 {
        e = 0.0;
    }

    let mut omega = e_vec.y.atan2(e_vec.x);
    if e == 0.0 {
        omega = 0.0;
    }

    let r_hat = if r > 0.0 {
        r_vec.scale(1.0 / r)
    } else {
        Vec2::zero()
    };
    let mut true_anomaly = r_hat.y.atan2(r_hat.x) - omega;
    true_anomaly = normalize_angle(true_anomaly);

    let cos_nu = true_anomaly.cos();
    let sin_nu = true_anomaly.sin();
    let cos_e = clamp((e + cos_nu) / (1.0 + e * cos_nu), -1.0, 1.0);
    let sin_e = clamp(
        (1.0 - e * e).max(0.0).sqrt() * sin_nu / (1.0 + e * cos_nu),
        -1.0,
        1.0,
    );
    let e_anom = sin_e.atan2(cos_e);
    let mean_anomaly = e_anom - e * e_anom.sin();

    OrbitState {
        semi_major_axis: a,
        eccentricity: e,
        arg_of_periapsis: omega,
        mean_anomaly_at_epoch: mean_anomaly,
        epoch: t,
    }
}

pub struct World {
    pub mu: f64,
    pub sim_time: f64,
    pub bodies: Vec<BodyState>,
    pub planet_radius: f64,
    pub interior: InteriorWorld,
    pub config: GameConfig,
    next_id: u64,
}

impl World {
    pub fn new(mu: f64, config: GameConfig) -> Self {
        let interior = InteriorWorld::new_test_ship(&config);
        Self {
            mu,
            sim_time: 0.0,
            bodies: Vec::new(),
            planet_radius: PLANET_RADIUS_M,
            interior,
            config,
            next_id: 1,
        }
    }

    pub fn add_body(&mut self, mut body: BodyState) -> u64 {
        if body.id == 0 {
            body.id = self.next_id;
            self.next_id += 1;
        }
        if let Some(shape) = &body.hull_shape {
            body.radius = shape.bounding_radius();
        }
        let (pos, vel) = orbit_to_cartesian(&body.orbit, self.mu, self.sim_time);
        body.position = pos;
        body.velocity = vel;
        let id = body.id;
        self.bodies.push(body);
        id
    }

    pub fn get_body_mut(&mut self, id: u64) -> Option<&mut BodyState> {
        self.bodies.iter_mut().find(|b| b.id == id)
    }

    pub fn step(&mut self, dt: f64) {
        self.sim_time += dt;
        for body in &mut self.bodies {
            let (pos, vel) = orbit_to_cartesian(&body.orbit, self.mu, self.sim_time);
            body.position = pos;
            body.velocity = vel;
        }
        self.cull_despawned_bodies();
        self.interior.step(dt, &self.config);
    }

    pub fn is_inside_gravity_well(&self, body: &BodyState) -> bool {
        body.position.length() <= GRAVITY_WELL_RADIUS_M
    }

    pub fn cull_despawned_bodies(&mut self) {
        self.bodies
            .retain(|body| body.position.length() <= DESPAWN_RADIUS_M);
    }

    pub fn apply_thrust_event(&mut self, event: &ThrustEvent) {
        let mu = self.mu;
        let sim_time = self.sim_time;
        if let Some(body) = self.get_body_mut(event.body_id) {
            let (pos_at_burn, vel_at_burn) = orbit_to_cartesian(&body.orbit, mu, event.time);
            let new_velocity = vel_at_burn.add(event.delta_v);
            let new_orbit = cartesian_to_orbit(pos_at_burn, new_velocity, mu, event.time);
            body.orbit = new_orbit;
            let (pos_now, vel_now) = orbit_to_cartesian(&body.orbit, mu, sim_time);
            body.position = pos_now;
            body.velocity = vel_now;
        }
    }

    pub fn detect_collisions(&self, dt: f64) -> Vec<CollisionEvent> {
        let target_time = self.sim_time + dt;
        let mut events = Vec::new();
        let mut future_states = Vec::with_capacity(self.bodies.len());
        for body in &self.bodies {
            future_states.push(orbit_to_cartesian(&body.orbit, self.mu, target_time));
        }

        for i in 0..self.bodies.len() {
            for j in (i + 1)..self.bodies.len() {
                let body_a = &self.bodies[i];
                let body_b = &self.bodies[j];
                let (pos_a, vel_a) = future_states[i];
                let (pos_b, vel_b) = future_states[j];
                let dist = pos_a.sub(pos_b).length();
                if dist <= body_a.radius + body_b.radius {
                    let relative_velocity = vel_b.sub(vel_a);
                    let contact_point = pos_a.add(pos_b).scale(0.5);
                    events.push(CollisionEvent {
                        time: target_time,
                        body_a: body_a.id,
                        body_b: body_b.id,
                        relative_velocity,
                        contact_point,
                    });
                }
            }
        }

        for (body, &(position, velocity)) in self.bodies.iter().zip(future_states.iter()) {
            let altitude = position.length();
            if altitude <= self.planet_radius + body.radius {
                let contact_point = if altitude > 1e-6 {
                    position.normalized().scale(self.planet_radius)
                } else {
                    Vec2::zero()
                };
                events.push(CollisionEvent {
                    time: target_time,
                    body_a: body.id,
                    body_b: 0,
                    relative_velocity: velocity,
                    contact_point,
                });
            }
        }

        events
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MU_EARTH: f64 = 3.986004418e14;

    fn approx_eq(a: f64, b: f64, eps: f64) {
        assert!((a - b).abs() <= eps, "{} !~= {} (tol {})", a, b, eps);
    }

    #[test]
    fn circular_orbit_invariance() {
        let a = 7_000_000.0;
        let orbit = OrbitState {
            semi_major_axis: a,
            eccentricity: 0.0,
            arg_of_periapsis: 0.0,
            mean_anomaly_at_epoch: 0.0,
            epoch: 0.0,
        };

        let speeds = [0.0, 100.0, 1_000.0, 10_000.0];
        let expected_speed = (MU_EARTH / a).sqrt();
        for t in speeds.iter().copied() {
            let (pos, vel) = orbit_to_cartesian(&orbit, MU_EARTH, t);
            approx_eq(pos.length(), a, 1e-3);
            approx_eq(vel.length(), expected_speed, 1e-6);
        }
    }

    #[test]
    fn round_trip_orbit_conversion() {
        let orbit = OrbitState {
            semi_major_axis: 20_000_000.0,
            eccentricity: 0.3,
            arg_of_periapsis: 1.2,
            mean_anomaly_at_epoch: -0.8,
            epoch: 1000.0,
        };
        let t = 1234.5;
        let (pos, vel) = orbit_to_cartesian(&orbit, MU_EARTH, t);
        let recovered = cartesian_to_orbit(pos, vel, MU_EARTH, t);
        approx_eq(recovered.semi_major_axis, orbit.semi_major_axis, 1e-3);
        approx_eq(recovered.eccentricity, orbit.eccentricity, 1e-9);
        approx_eq(recovered.arg_of_periapsis, orbit.arg_of_periapsis, 1e-9);
    }

    #[test]
    fn thrust_event_changes_orbit() {
        let mut world = World::new(MU_EARTH, GameConfig::default());
        let a = 7_000_000.0;
        let body = BodyState {
            id: 0,
            mass: 1_000.0,
            radius: 5.0,
            orbit: OrbitState {
                semi_major_axis: a,
                eccentricity: 0.0,
                arg_of_periapsis: 0.0,
                mean_anomaly_at_epoch: 0.0,
                epoch: 0.0,
            },
            position: Vec2::zero(),
            velocity: Vec2::zero(),
            body_type: BodyType::Ship,
            hull_shape: None,
        };
        let body_id = world.add_body(body);

        let burn_time = 500.0;
        let (pos, _vel) = orbit_to_cartesian(
            &world.bodies.iter().find(|b| b.id == body_id).unwrap().orbit,
            world.mu,
            burn_time,
        );
        let radial_dir = pos.normalized();
        let delta_v = radial_dir.scale(50.0);
        let event = ThrustEvent {
            body_id,
            time: burn_time,
            delta_v,
            thrust_type: ThrustType::Chemical,
        };
        world.apply_thrust_event(&event);
        let body = world.bodies.iter().find(|b| b.id == body_id).unwrap();
        assert!(body.orbit.eccentricity > 0.0);
        assert!((body.orbit.semi_major_axis - a).abs() > 1.0);
    }
}

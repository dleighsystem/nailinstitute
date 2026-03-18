"""
dese.systems — Chaotic dynamical systems for entropy generation.
================================================================

Each system implements the ``ChaoticSystem`` protocol:
    - ``state``      — current state vector (tuple of floats)
    - ``step()``     — advance one integration step (deterministic)
    - ``state_bytes()`` — serialise current state to bytes (IEEE 754 LE)

All arithmetic uses Python ``float`` (IEEE 754 binary64).  Integration
uses fixed-step RK4 to guarantee bit-exact reproducibility across
platforms.  No adaptive step-sizing, no platform-dependent libm calls.

Supported systems
-----------------
- ``LorenzSystem``    — Lorenz (1963) 3-variable attractor
- ``RosslerSystem``   — Rössler (1976) 3-variable attractor
- ``ChuaSystem``      — Chua (1983) 3-variable double-scroll
- ``ChenSystem``      — Chen (1999) 3-variable attractor
- ``HyperLorenz``     — 4D hyperchaotic Lorenz extension
- ``DoublePendulum``  — Hamiltonian double pendulum (4-variable)
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Tuple


# ─── IEEE 754 binary64 little-endian packer ──────────────────────────

def _pack_le(*values: float) -> bytes:
    """Pack N float64 values as little-endian IEEE 754 bytes."""
    return struct.pack(f"<{len(values)}d", *values)


# ─── Abstract base ───────────────────────────────────────────────────

class ChaoticSystem(ABC):
    """Protocol for a deterministic chaotic dynamical system."""

    @property
    @abstractmethod
    def state(self) -> Tuple[float, ...]:
        """Current state vector."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Number of state variables."""

    @abstractmethod
    def derivatives(self, s: Tuple[float, ...]) -> Tuple[float, ...]:
        """Compute ds/dt at a given state vector *s*."""

    @property
    @abstractmethod
    def dt(self) -> float:
        """Fixed integration time-step."""

    def step(self) -> None:
        """Advance state by one RK4 step (deterministic, fixed-step)."""
        s = self.state
        h = self.dt
        n = self.dimension

        k1 = self.derivatives(s)
        s2 = tuple(s[i] + 0.5 * h * k1[i] for i in range(n))
        k2 = self.derivatives(s2)
        s3 = tuple(s[i] + 0.5 * h * k2[i] for i in range(n))
        k3 = self.derivatives(s3)
        s4 = tuple(s[i] + h * k3[i] for i in range(n))
        k4 = self.derivatives(s4)

        new = tuple(
            s[i] + (h / 6.0) * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i])
            for i in range(n)
        )
        self._set_state(new)

    @abstractmethod
    def _set_state(self, new: Tuple[float, ...]) -> None:
        """Replace the internal state vector."""

    def state_bytes(self) -> bytes:
        """Serialise current state as little-endian IEEE 754 binary64."""
        return _pack_le(*self.state)

    def advance(self, steps: int) -> None:
        """Advance multiple steps."""
        for _ in range(steps):
            self.step()


# ─── Lorenz (1963) ───────────────────────────────────────────────────

@dataclass
class LorenzSystem(ChaoticSystem):
    """
    Lorenz attractor.

        dx/dt = σ(y − x)
        dy/dt = x(ρ − z) − y
        dz/dt = xy − βz

    Default parameters (σ=10, ρ=28, β=8/3) produce the classic
    butterfly attractor with Lyapunov exponent λ₁ ≈ 0.906.
    """
    sigma: float = 10.0
    rho: float = 28.0
    beta: float = 8.0 / 3.0
    x: float = 1.0
    y: float = 1.0
    z: float = 1.0
    _dt: float = 0.005

    @property
    def state(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def dimension(self) -> int:
        return 3

    @property
    def dt(self) -> float:
        return self._dt

    def derivatives(self, s: Tuple[float, ...]) -> Tuple[float, ...]:
        x, y, z = s
        return (
            self.sigma * (y - x),
            x * (self.rho - z) - y,
            x * y - self.beta * z,
        )

    def _set_state(self, new: Tuple[float, ...]) -> None:
        self.x, self.y, self.z = new


# ─── Rössler (1976) ──────────────────────────────────────────────────

@dataclass
class RosslerSystem(ChaoticSystem):
    """
    Rössler attractor.

        dx/dt = −y − z
        dy/dt = x + ay
        dz/dt = b + z(x − c)

    Default: a=0.2, b=0.2, c=5.7 → single-scroll chaos.
    """
    a: float = 0.2
    b: float = 0.2
    c: float = 5.7
    x: float = 1.0
    y: float = 1.0
    z: float = 0.0
    _dt: float = 0.01

    @property
    def state(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def dimension(self) -> int:
        return 3

    @property
    def dt(self) -> float:
        return self._dt

    def derivatives(self, s: Tuple[float, ...]) -> Tuple[float, ...]:
        x, y, z = s
        return (
            -y - z,
            x + self.a * y,
            self.b + z * (x - self.c),
        )

    def _set_state(self, new: Tuple[float, ...]) -> None:
        self.x, self.y, self.z = new


# ─── Chua (1983) ─────────────────────────────────────────────────────

@dataclass
class ChuaSystem(ChaoticSystem):
    """
    Chua's circuit — canonical piecewise-linear chaotic oscillator.

        dx/dt = α [y − x − f(x)]
        dy/dt = x − y + z
        dz/dt = −β y

    where f(x) = m₁ x + 0.5(m₀ − m₁)(|x + 1| − |x − 1|)

    Default: α=15.6, β=28.58, m₀=−1.143, m₁=−0.714 → double scroll.
    """
    alpha: float = 15.6
    beta_param: float = 28.58   # 'beta' clashes with dataclass reserved
    m0: float = -1.143
    m1: float = -0.714
    x: float = 0.7
    y: float = 0.0
    z: float = 0.0
    _dt: float = 0.001

    @property
    def state(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def dimension(self) -> int:
        return 3

    @property
    def dt(self) -> float:
        return self._dt

    def _chua_f(self, x: float) -> float:
        return self.m1 * x + 0.5 * (self.m0 - self.m1) * (abs(x + 1.0) - abs(x - 1.0))

    def derivatives(self, s: Tuple[float, ...]) -> Tuple[float, ...]:
        x, y, z = s
        return (
            self.alpha * (y - x - self._chua_f(x)),
            x - y + z,
            -self.beta_param * y,
        )

    def _set_state(self, new: Tuple[float, ...]) -> None:
        self.x, self.y, self.z = new


# ─── Chen (1999) ─────────────────────────────────────────────────────

@dataclass
class ChenSystem(ChaoticSystem):
    """
    Chen attractor — dual of the Lorenz system.

        dx/dt = a(y − x)
        dy/dt = (c − a)x − xz + cy
        dz/dt = xy − bz

    Default: a=35, b=3, c=28 → Chen chaos.
    """
    a: float = 35.0
    b: float = 3.0
    c: float = 28.0
    x: float = -10.0
    y: float = 0.0
    z: float = 37.0
    _dt: float = 0.002

    @property
    def state(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def dimension(self) -> int:
        return 3

    @property
    def dt(self) -> float:
        return self._dt

    def derivatives(self, s: Tuple[float, ...]) -> Tuple[float, ...]:
        x, y, z = s
        return (
            self.a * (y - x),
            (self.c - self.a) * x - x * z + self.c * y,
            x * y - self.b * z,
        )

    def _set_state(self, new: Tuple[float, ...]) -> None:
        self.x, self.y, self.z = new


# ─── Hyper-Lorenz (4D) ──────────────────────────────────────────────

@dataclass
class HyperLorenz(ChaoticSystem):
    """
    4D Hyperchaotic Lorenz system (Wang & Wang, 2008).

        dx/dt = a(y − x) + w
        dy/dt = cx − y − xz
        dz/dt = xy − bz
        dw/dt = −yz + dw

    Two positive Lyapunov exponents → hyperchaos (more entropy/step).
    """
    a: float = 10.0
    b: float = 8.0 / 3.0
    c: float = 28.0
    d: float = -1.0
    x: float = 1.0
    y: float = 1.0
    z: float = 1.0
    w: float = 1.0
    _dt: float = 0.005

    @property
    def state(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.z, self.w)

    @property
    def dimension(self) -> int:
        return 4

    @property
    def dt(self) -> float:
        return self._dt

    def derivatives(self, s: Tuple[float, ...]) -> Tuple[float, ...]:
        x, y, z, w = s
        return (
            self.a * (y - x) + w,
            self.c * x - y - x * z,
            x * y - self.b * z,
            -y * z + self.d * w,
        )

    def _set_state(self, new: Tuple[float, ...]) -> None:
        self.x, self.y, self.z, self.w = new


# ─── Double Pendulum (Hamiltonian, 4D) ──────────────────────────────

@dataclass
class DoublePendulum(ChaoticSystem):
    """
    Hamiltonian double pendulum in angle-momentum coordinates.

    State: (θ₁, θ₂, p₁, p₂)  — angles and conjugate momenta.

    Masses m₁ = m₂ = 1, lengths L₁ = L₂ = 1, g = 9.81.
    Equations derived from the Lagrangian; full chaotic regime
    for moderate initial angles.
    """
    m1: float = 1.0
    m2: float = 1.0
    L1: float = 1.0
    L2: float = 1.0
    g: float = 9.81
    theta1: float = 2.0       # radians — well into chaotic regime
    theta2: float = 2.0
    p1: float = 0.0
    p2: float = 0.0
    _dt: float = 0.001

    @property
    def state(self) -> Tuple[float, float, float, float]:
        return (self.theta1, self.theta2, self.p1, self.p2)

    @property
    def dimension(self) -> int:
        return 4

    @property
    def dt(self) -> float:
        return self._dt

    def derivatives(self, s: Tuple[float, ...]) -> Tuple[float, ...]:
        t1, t2, p1, p2 = s
        m1, m2, L1, L2, g = self.m1, self.m2, self.L1, self.L2, self.g
        import math
        cos_d = math.cos(t1 - t2)
        sin_d = math.sin(t1 - t2)
        denom = m1 + m2 * (1.0 - cos_d * cos_d)

        # Angular velocities from momenta
        w1 = (L2 * p1 - L1 * cos_d * p2) / (L1 * L1 * L2 * denom)
        w2 = (-L2 * cos_d * p1 + L1 * (m1 + m2) * p2) / (m2 * L1 * L2 * L2 * denom)

        # Common sub-expression
        A = (p1 * p2 * sin_d) / (L1 * L2 * denom)
        B = (L2 * L2 * m2 * w1 * w1 + L1 * L1 * (m1 + m2) * w2 * w2
             - 2.0 * L1 * L2 * m2 * w1 * w2 * cos_d)
        C = sin_d * cos_d / (2.0 * L1 * L2 * denom * denom)
        # NOTE: We use math.sin not numpy to stay deterministic
        dp1 = -(m1 + m2) * g * L1 * math.sin(t1) - A + B * C
        dp2 = -m2 * g * L2 * math.sin(t2) + A - B * C

        return (w1, w2, dp1, dp2)

    def _set_state(self, new: Tuple[float, ...]) -> None:
        self.theta1, self.theta2, self.p1, self.p2 = new


# ─── Registry ────────────────────────────────────────────────────────

SYSTEMS: dict[str, type[ChaoticSystem]] = {
    "lorenz": LorenzSystem,
    "rossler": RosslerSystem,
    "chua": ChuaSystem,
    "chen": ChenSystem,
    "hyper_lorenz": HyperLorenz,
    "double_pendulum": DoublePendulum,
}


def create_system(name: str, **overrides) -> ChaoticSystem:
    """Instantiate a chaotic system by name with optional param overrides."""
    cls = SYSTEMS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown system '{name}'. Available: {sorted(SYSTEMS.keys())}"
        )
    return cls(**overrides)

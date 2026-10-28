"""Explicit error types (CLAUDE.md conventions)."""


class ConfigError(Exception):
    """Invalid or missing configuration key."""


class CarbonDataError(Exception):
    """Carbon data violates the gap rules of PRD §6.2."""


class MigrationError(Exception):
    """Attempt to move or remove a running job (no migration, PRD §8)."""


class SimulationInvariantError(Exception):
    """An invariant of the simulation was violated."""


class DeploymentError(Exception):
    """Transport failure in the deployment track (PRD §13.5)."""


class ChecksumError(Exception):
    """A raw archive does not match its published SHA-256."""

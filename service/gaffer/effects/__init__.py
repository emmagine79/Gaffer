"""Software effects. Importing this package registers every effect."""

from . import ambient, cinematic, nature, party, signature  # noqa: F401  (registration side effect)
from .base import REGISTRY, Effect, Frame, Param

__all__ = ["REGISTRY", "Effect", "Frame", "Param"]

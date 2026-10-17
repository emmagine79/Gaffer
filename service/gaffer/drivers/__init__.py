"""Driver registry.

Every sub-package of ``gaffer/drivers/`` is a brand. The registry imports each one and
registers the concrete ``Driver`` classes that package defines, so a new brand is a new
folder and no existing file changes. One package that fails to import, or one driver
that fails to build, is skipped with a reason; the others still load.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field

from .base import Advert, Driver, DriverContext, LightStatus

logger = logging.getLogger(__name__)

__all__ = ["Advert", "Driver", "DriverContext", "LightStatus", "Registry", "build_drivers", "discover"]

#: The methods a class must have to count as a driver when it does not subclass ``Driver``.
_CONTRACT = ("match", "connect", "apply", "identify", "status", "start", "stop")


@dataclass(slots=True)
class Registry:
    """The drivers that loaded, by id, and the ones that did not."""

    drivers: dict[str, Driver] = field(default_factory=dict)
    #: ``{"driver": folder or id, "reason": plain words}``. Never a path.
    skipped: list[dict[str, str]] = field(default_factory=list)
    _missing: dict[str, Driver] = field(default_factory=dict)

    def get(self, driver_id: str) -> Driver | None:
        return self.drivers.get(driver_id)

    def for_driver(self, driver_id: str) -> Driver:
        """The driver with this id, or a stand-in that reports its lights unreachable."""
        found = self.drivers.get(driver_id)
        if found is None:
            from .missing import MissingDriver

            found = self._missing.setdefault(driver_id, MissingDriver(driver_id))
        return found

    def match(self, advert: Advert) -> tuple[Driver, str] | None:
        """The first driver that recognises ``advert``, with the model id it gave."""
        for driver in self.drivers.values():
            try:
                model_id = driver.match(advert)
            except Exception:  # one driver's bug must not hide the others' lights
                logger.exception("driver %s failed to match an advertisement", driver.id)
                continue
            if model_id:
                return driver, model_id
        return None


def _is_driver_class(obj: object, module: str) -> bool:
    if not inspect.isclass(obj) or obj is Driver or not str(getattr(obj, "__module__", "")).startswith(module):
        return False
    if not isinstance(getattr(obj, "id", None), str) or not obj.id or inspect.isabstract(obj):
        return False
    return issubclass(obj, Driver) or all(callable(getattr(obj, name, None)) for name in _CONTRACT)


def discover(skipped: list[dict[str, str]] | None = None) -> dict[str, type[Driver]]:
    """Import every driver package and return its driver classes by id."""
    skipped = skipped if skipped is not None else []
    found: dict[str, type[Driver]] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module_name = f"{__name__}.{info.name}"
        try:
            package = importlib.import_module(module_name)
        except Exception:  # a broken brand never stops the others
            logger.exception("driver package %s failed to import", info.name)
            skipped.append({"driver": info.name, "reason": "could not be imported"})
            continue
        classes = {}
        for _name, obj in inspect.getmembers(package, inspect.isclass):
            if _is_driver_class(obj, module_name):
                classes[obj.id] = obj
        if not classes:
            skipped.append({"driver": info.name, "reason": "defines no driver"})
        for driver_id, cls in classes.items():
            if driver_id in found:
                skipped.append({"driver": driver_id, "reason": "id already taken"})
                continue
            found[driver_id] = cls
    return found


def build_drivers(context: DriverContext | None = None, *, demo: bool = False) -> Registry:
    """Build one instance of every driver. In demo mode the stand-in ``demo`` driver joins them."""
    context = context or DriverContext(demo=demo)
    registry = Registry()
    for driver_id, cls in discover(registry.skipped).items():
        try:
            registry.drivers[driver_id] = cls(context)
        except Exception:
            logger.exception("driver %s failed to build", driver_id)
            registry.skipped.append({"driver": driver_id, "reason": "could not be built"})
    if demo:
        from .demo import DemoDriver

        registry.drivers["demo"] = DemoDriver(context)
    return registry

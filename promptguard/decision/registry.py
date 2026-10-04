"""Select a Predictor by name so the runner and evaluation can swap implementations."""

from __future__ import annotations

import os
from collections.abc import Callable

from promptguard.decision.base import Predictor
from promptguard.decision.mock_predictor import MockPredictor


PREDICTOR_ENV = "PROMPTGUARD_PREDICTOR"
DEFAULT_PREDICTOR = "mock"

PredictorFactory = Callable[[], Predictor]

_FACTORIES: dict[str, PredictorFactory] = {
    "mock": MockPredictor,
}


def register_predictor(name: str, factory: PredictorFactory) -> None:
    """Add a named predictor, e.g. a real model or one variant per decision threshold."""
    _FACTORIES[name] = factory


def available_predictors() -> list[str]:
    return sorted(_FACTORIES)


def load_predictor(name: str | None = None) -> Predictor:
    """Build the predictor named explicitly, else by $PROMPTGUARD_PREDICTOR, else the mock."""
    selected = name or os.environ.get(PREDICTOR_ENV) or DEFAULT_PREDICTOR
    try:
        factory = _FACTORIES[selected]
    except KeyError:
        raise ValueError(f"unknown predictor {selected!r}; available: {available_predictors()}") from None
    return factory()

"""Validated, immutable processing settings shared by the GUI and worker."""

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HdrSettings:
    luminance: int = 650
    contrast: int = 100
    saturation: int = 100
    middle_gray: int = 50
    debanding: bool = True
    exposure: float = 0.0
    transfer: str = "srgb"
    background: str = "black"
    device: int = 0

    def __post_init__(self) -> None:
        for name, low, high in (
            ("luminance", 400, 2000),
            ("contrast", 0, 200),
            ("saturation", 0, 200),
            ("middle_gray", 10, 100),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}.")
        if (
            type(self.exposure) not in (int, float)
            or not math.isfinite(self.exposure)
            or not -3 <= self.exposure <= 3
        ):
            raise ValueError("Exposure must be finite and between -3 and +3 EV.")
        if self.transfer not in ("srgb", "gamma22"):
            raise ValueError("Input transfer must be srgb or gamma22.")
        if self.background not in ("black", "white"):
            raise ValueError("Background must be black or white.")
        if type(self.debanding) is not bool:
            raise ValueError("Debanding must be a boolean.")
        if type(self.device) is not int or self.device < 0:
            raise ValueError("Device must be a non-negative integer.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HdrSettings":
        if not isinstance(data, dict):
            raise ValueError("Settings must be a JSON object.")
        unknown = data.keys() - cls.__dataclass_fields__.keys()
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
        return cls(**data)

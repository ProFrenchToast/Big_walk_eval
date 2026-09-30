"""Pixel <-> camera angle conversion for "look toward the pixel"."""

from __future__ import annotations

import math

from big_walk_eval.protocol import SCREEN_HEIGHT, SCREEN_WIDTH


def focal_px(hfov_deg: float, width: int = SCREEN_WIDTH) -> float:
    return (width / 2) / math.tan(math.radians(hfov_deg) / 2)


def pixel_to_angles(
    x: float,
    y: float,
    hfov_deg: float,
    width: int = SCREEN_WIDTH,
    height: int = SCREEN_HEIGHT,
) -> tuple[float, float]:
    """Angles that turn the camera so pixel (x, y) moves to the screen center.

    Returns (dyaw_deg, dpitch_deg). Positive yaw turns right, positive pitch looks down.
    """
    f = focal_px(hfov_deg, width)
    dyaw = math.degrees(math.atan((x - width / 2) / f))
    dpitch = math.degrees(math.atan((y - height / 2) / f))
    return dyaw, dpitch


def angles_to_pixel(
    dyaw_deg: float,
    dpitch_deg: float,
    hfov_deg: float,
    width: int = SCREEN_WIDTH,
    height: int = SCREEN_HEIGHT,
) -> tuple[int, int]:
    """Inverse of `pixel_to_angles`, rounded to whole pixels. Angles must be inside the view."""
    f = focal_px(hfov_deg, width)
    x = width / 2 + f * math.tan(math.radians(dyaw_deg))
    y = height / 2 + f * math.tan(math.radians(dpitch_deg))
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"angles ({dyaw_deg}, {dpitch_deg}) are outside the view")
    return round(x), round(y)


def vfov_to_hfov(vfov_deg: float, width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT) -> float:
    """Unity's `Camera.fieldOfView` is vertical. Convert it for the given aspect ratio."""
    half = math.atan(math.tan(math.radians(vfov_deg) / 2) * width / height)
    return math.degrees(2 * half)

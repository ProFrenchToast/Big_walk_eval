"""Draw FakeGame views with Pillow: a first-person raycast view and a top-down overview."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Literal

from PIL import Image, ImageDraw, ImageFont

from big_walk_eval.look import focal_px
from big_walk_eval.protocol import SCREEN_HEIGHT, SCREEN_WIDTH

if TYPE_CHECKING:
    from big_walk_eval.game.fake_game import FakeBody, FakeGame, Wall

EYE_H = 1.6
WALL_H = 3.0
COL_STEP = 2
SKY = (172, 206, 236)
GROUND = (118, 162, 96)
WALL_COLORS = {"boundary": (150, 150, 162), "wall": (164, 122, 88), "gate": (205, 60, 50)}
PLATE_UP = (235, 205, 60)
PLATE_DOWN = (120, 200, 90)
GOURD = (236, 140, 36)
STICK = (110, 74, 40)
BODY_COLORS = [(70, 110, 220), (220, 80, 150), (90, 190, 190), (160, 100, 220)]


@cache
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _shade(color: tuple[int, int, int], dist: float) -> tuple[int, int, int]:
    k = max(0.45, 1.0 - dist / 40.0)
    return (int(color[0] * k), int(color[1] * k), int(color[2] * k))


def _ray_segment(ox: float, oz: float, dx: float, dz: float, w: Wall) -> float | None:
    sx, sz = w.x2 - w.x1, w.z2 - w.z1
    denom = dx * sz - dz * sx
    if abs(denom) < 1e-12:
        return None
    ax, az = w.x1 - ox, w.z1 - oz
    t = (ax * sz - az * sx) / denom
    u = (ax * dz - az * dx) / denom
    if t > 1e-6 and 0.0 <= u <= 1.0:
        return t
    return None


def _ray_circle(
    ox: float, oz: float, dx: float, dz: float, cx: float, cz: float, r: float
) -> tuple[float, float] | None:
    fx, fz = ox - cx, oz - cz
    b = fx * dx + fz * dz
    c = fx * fx + fz * fz - r * r
    disc = b * b - c
    if disc < 0:
        return None
    s = math.sqrt(disc)
    t0, t1 = -b - s, -b + s
    if t1 <= 0:
        return None
    return max(t0, 0.05), t1


@dataclass
class _Billboard:
    x: float
    z: float
    width: float
    base: float
    height: float
    color: tuple[int, int, int]
    shape: Literal["rect", "ellipse"]
    label: str = ""


def first_person(game: FakeGame, viewer: FakeBody) -> bytes:
    return _png(first_person_image(game, viewer))


def first_person_image(game: FakeGame, viewer: FakeBody) -> Image.Image:
    from big_walk_eval.game.fake_game import HFOV_DEG, PLATE_RADIUS, PLATE_XZ

    w, h = SCREEN_WIDTH, SCREEN_HEIGHT
    f = focal_px(HFOV_DEG, w)
    img = Image.new("RGB", (w, h), SKY)
    draw = ImageDraw.Draw(img)
    horizon = h / 2 - f * math.tan(math.radians(viewer.pitch))
    draw.rectangle([0, max(0.0, horizon), w, h], fill=GROUND)

    yaw = math.radians(viewer.yaw)
    fwd = (math.sin(yaw), math.cos(yaw))
    right = (fwd[1], -fwd[0])
    walls = game.blocking_walls()
    cols = list(range(0, w, COL_STEP))
    depth = [math.inf] * len(cols)
    plate_color = PLATE_DOWN if game.gate_open else PLATE_UP

    for ci, x in enumerate(cols):
        off = math.atan((x + COL_STEP / 2 - w / 2) / f)
        ang = yaw + off
        dx, dz = math.sin(ang), math.cos(ang)
        cos_off = math.cos(off)
        best, kind = math.inf, None
        for wall in walls:
            t = _ray_segment(viewer.x, viewer.z, dx, dz, wall)
            if t is not None and t < best:
                best, kind = t, wall.kind
        if kind is not None:
            perp = best * cos_off
            depth[ci] = perp
            top = horizon - f * (WALL_H - EYE_H) / perp
            bottom = horizon + f * EYE_H / perp
            draw.rectangle([x, top, x + COL_STEP - 1, bottom], fill=_shade(WALL_COLORS[kind], perp))
        hit = _ray_circle(viewer.x, viewer.z, dx, dz, *PLATE_XZ, PLATE_RADIUS)
        if hit is not None and hit[0] < best:
            near, far = hit[0] * cos_off, min(hit[1], best) * cos_off
            y_far = horizon + f * EYE_H / far
            y_near = min(h, horizon + f * EYE_H / near)
            if y_far < y_near:
                draw.rectangle([x, y_far, x + COL_STEP - 1, y_near], fill=plate_color)

    boards: list[_Billboard] = []
    for body in game.bodies.values():
        if body.slot == viewer.slot:
            continue
        color = BODY_COLORS[(body.slot - 1) % len(BODY_COLORS)]
        boards.append(_Billboard(body.x, body.z, 0.6, 0.0, 1.35, color, "rect", body.name))
        boards.append(_Billboard(body.x, body.z, 0.45, 1.3, 0.45, color, "ellipse"))
    for item in game.items.values():
        if item.holder is not None and item.holder[0] == viewer.slot:
            continue
        ix, iz = game.item_position(item)
        base = 0.0 if item.holder is None else 0.9
        if item.is_reward:
            boards.append(_Billboard(ix, iz, 0.45, base, 0.55, GOURD, "ellipse"))
        else:
            boards.append(_Billboard(ix, iz, 0.12, base, 0.9, STICK, "rect"))

    def cam(b: _Billboard) -> tuple[float, float]:
        rx, rz = b.x - viewer.x, b.z - viewer.z
        return rx * right[0] + rz * right[1], rx * fwd[0] + rz * fwd[1]

    visible = [(b, *cam(b)) for b in boards]
    visible = [v for v in visible if v[2] > 0.2]
    visible.sort(key=lambda v: -v[2])
    labels: list[tuple[float, float, str]] = []
    for b, xc, zc in visible:
        cx = w / 2 + f * xc / zc
        half = f * b.width / zc / 2
        top = horizon + f * (EYE_H - b.base - b.height) / zc
        bottom = horizon + f * (EYE_H - b.base) / zc
        mid, hh = (top + bottom) / 2, (bottom - top) / 2
        drawn = False
        for ci, x in enumerate(cols):
            xm = x + COL_STEP / 2
            if abs(xm - cx) > half or depth[ci] <= zc:
                continue
            if b.shape == "ellipse":
                u = (xm - cx) / half
                s = math.sqrt(max(0.0, 1 - u * u))
                draw.rectangle([x, mid - hh * s, x + COL_STEP - 1, mid + hh * s], fill=b.color)
            else:
                draw.rectangle([x, top, x + COL_STEP - 1, bottom], fill=b.color)
            drawn = True
        if drawn and b.label:
            labels.append((cx, top - f * 0.6 / zc, b.label))
    for cx, y, text in labels:
        draw.text((cx, y), text, fill=(20, 20, 20), anchor="ms", font=_font(22))

    cx, cy = w // 2, h // 2
    draw.line([cx - 10, cy, cx + 10, cy], fill=(255, 255, 255), width=2)
    draw.line([cx, cy - 10, cx, cy + 10], fill=(255, 255, 255), width=2)
    hands = []
    for hand in ("left", "right"):
        item_id = viewer.held.get(hand)
        hands.append(f"{hand} hand: {game.items[item_id].type if item_id else 'empty'}")
    draw.rectangle([10, h - 44, 430, h - 10], fill=(0, 0, 0))
    draw.text((20, h - 27), "   ".join(hands), fill=(255, 255, 255), anchor="lm", font=_font(20))
    return img


def overview(game: FakeGame) -> bytes:
    from big_walk_eval.game.fake_game import HALF_SIZE, PLATE_RADIUS, PLATE_XZ, WALLS

    w, h = SCREEN_WIDTH, SCREEN_HEIGHT
    img = Image.new("RGB", (w, h), GROUND)
    draw = ImageDraw.Draw(img)
    scale = (h - 60) / (2 * HALF_SIZE)

    def px(x: float, z: float) -> tuple[float, float]:
        return w / 2 + x * scale, h / 2 - z * scale

    px0, pz0 = PLATE_XZ
    r = PLATE_RADIUS * scale
    ppx, ppz = px(px0, pz0)
    draw.ellipse(
        [ppx - r, ppz - r, ppx + r, ppz + r], fill=PLATE_DOWN if game.gate_open else PLATE_UP
    )
    for wall in WALLS:
        if wall.kind == "gate" and game.gate_open:
            continue
        draw.line(
            [px(wall.x1, wall.z1), px(wall.x2, wall.z2)], fill=WALL_COLORS[wall.kind], width=5
        )
    for item in game.items.values():
        ix, iz = px(*game.item_position(item))
        color = GOURD if item.is_reward else STICK
        draw.ellipse([ix - 7, iz - 7, ix + 7, iz + 7], fill=color, outline=(0, 0, 0))
    for body in game.bodies.values():
        bx, bz = px(body.x, body.z)
        fx, fz = body.forward()
        color = BODY_COLORS[(body.slot - 1) % len(BODY_COLORS)]
        draw.ellipse([bx - 10, bz - 10, bx + 10, bz + 10], fill=color, outline=(0, 0, 0))
        draw.line([bx, bz, bx + fx * 25, bz - fz * 25], fill=(0, 0, 0), width=3)
        draw.text((bx + 14, bz - 14), body.name, fill=(0, 0, 0), font=_font(20))
    draw.text((20, 20), f"t = {game.game_ms} ms", fill=(0, 0, 0), font=_font(20))
    return _png(img)

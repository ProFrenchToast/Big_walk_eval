"""Measure mouse counts per degree of camera turn. Run once per machine.

Stop the game server first: this script opens its own connection to the
bridge mod and sends real mouse input. Have a body active in the game, then:
    uv run python -m server.calibrate --config server.yaml
and copy `counts_per_degree` and `invert_mouse_y` into the server config.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from server.bridge_client import BridgeClient
from server.input.backend import InputBackend


@dataclass
class Calibration:
    counts_per_degree: float
    pitch_counts_per_degree: float
    invert_mouse_y: bool
    yaw_samples: list[float]
    pitch_samples: list[float]


def wrap_deg(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


async def _active_angles(bridge: BridgeClient) -> tuple[float, float]:
    state = await bridge.get_state()
    body = next(b for b in state.bodies if b.slot == state.active_slot)
    return body.yaw_deg, body.pitch_deg


async def _turn(
    bridge: BridgeClient,
    input: InputBackend,
    dx: int,
    dy: int,
    step: int,
    settle_s: float,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    n = max(1, max(abs(dx), abs(dy)) // step)
    sent_x = sent_y = 0
    await bridge.resume()
    try:
        for i in range(1, n + 1):
            x, y = round(dx * i / n), round(dy * i / n)
            await input.move_rel(x - sent_x, y - sent_y)
            sent_x, sent_y = x, y
            await sleep(0.01)
        await sleep(settle_s)
    finally:
        await bridge.pause()


async def calibrate(
    bridge: BridgeClient,
    input: InputBackend,
    counts: int = 600,
    trials: int = 3,
    step: int = 20,
    settle_s: float = 0.3,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Calibration:
    await input.focus()
    yaw_samples, pitch_samples = [], []
    pitch_counts = max(step, counts // 3)
    for _ in range(trials):
        yaw0, _ = await _active_angles(bridge)
        await _turn(bridge, input, counts, 0, step, settle_s, sleep)
        yaw1, _ = await _active_angles(bridge)
        await _turn(bridge, input, -counts, 0, step, settle_s, sleep)
        yaw_samples.append(counts / wrap_deg(yaw1 - yaw0))

        _, pitch0 = await _active_angles(bridge)
        await _turn(bridge, input, 0, pitch_counts, step, settle_s, sleep)
        _, pitch1 = await _active_angles(bridge)
        await _turn(bridge, input, 0, -pitch_counts, step, settle_s, sleep)
        pitch_samples.append(pitch_counts / (pitch1 - pitch0))

    pitch_cpd = statistics.median(pitch_samples)
    return Calibration(
        counts_per_degree=statistics.median(yaw_samples),
        pitch_counts_per_degree=abs(pitch_cpd),
        invert_mouse_y=pitch_cpd < 0,
        yaw_samples=yaw_samples,
        pitch_samples=pitch_samples,
    )


async def _main(config_path: str | None, counts: int, trials: int) -> None:
    from server.config import ServerConfig
    from server.input.sendinput import SendInputBackend

    config = ServerConfig.load(config_path)
    bridge = BridgeClient(config.bridge_host, config.bridge_port, config.bridge_timeout_s)
    input = SendInputBackend(config.window_title)
    try:
        result = await calibrate(bridge, input, counts=counts, trials=trials)
    finally:
        await input.release_all()
        await bridge.close()
    print(f"yaw samples: {[round(s, 3) for s in result.yaw_samples]}")
    print(f"pitch samples: {[round(s, 3) for s in result.pitch_samples]}")
    print(f"counts_per_degree: {result.counts_per_degree:.4f}")
    print(f"invert_mouse_y: {str(result.invert_mouse_y).lower()}")
    if (
        abs(result.pitch_counts_per_degree - result.counts_per_degree)
        > 0.1 * result.counts_per_degree
    ):
        print(
            f"warning: pitch uses {result.pitch_counts_per_degree:.4f} counts per degree. "
            "The server assumes one value for both axes."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--counts", type=int, default=600)
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(_main(args.config, args.counts, args.trials))


if __name__ == "__main__":
    main()

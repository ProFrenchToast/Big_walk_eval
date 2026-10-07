"""Compose the per-body capture frames of an episode into one video.

Each body gets a tile with its own view. A yellow border marks the body that
acts. Each tile captions the messages that its body sent in the in-game chat.
The other views show a message only where the game shows it, over the
speaker's head. The messages (`text_chat` events) and the active body come
from the episode recording (`EpisodeLog.replay`), matched to the frames by
game time. A message gets the game time at the end of the act that sent it.

Frames exist only while game time runs, so the video skips the pauses
between actions. With `hold_s` above 0, each chat message freezes the video
for that many seconds so that viewers can read it. The default is 0: the
video then lasts as long as the game time, and each caption stays on screen
for `caption_s` seconds of game time.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from big_walk_eval.protocol import CaptureInfo
from big_walk_eval.replay import ActStep, CaptureStep, Recording

ACTIVE = (250, 204, 21)
IDLE = (40, 40, 46)
BACKGROUND = (18, 18, 22)
TEXT = (240, 240, 240)
HEADER_H = 36
BORDER = 5


@dataclass(frozen=True)
class Caption:
    game_ms: int
    speaker: str
    text: str
    slots: frozenset[int]


@dataclass(frozen=True)
class VideoFrame:
    index: int
    """Capture frame to show."""
    game_ms: float
    """Game time since the capture started."""


@cache
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


class Composer:
    def __init__(
        self,
        info: CaptureInfo,
        directory: Path | None = None,
        recording: Recording | None = None,
        slots: list[int] | None = None,
        caption_s: float = 5.0,
        hold_s: float = 0.0,
        max_captions: int = 3,
    ) -> None:
        self.info = info
        self.directory = Path(directory or info.directory)
        self.slots = slots or sorted(info.slots)
        unknown = [s for s in self.slots if s not in info.slots]
        if unknown:
            raise ValueError(f"no frames for slots {unknown}")
        self.caption_ms = caption_s * 1000
        self.hold_frames = round(hold_s * info.fps)
        self.max_captions = max_captions
        self.step_ms = 1000 / info.fps
        self.acts: list[ActStep] = []
        self.captions: list[Caption] = []
        if recording is not None:
            # Frame times count from the start of the capture, recorded times from the reset.
            start = next((s.game_ms for s in recording.steps if isinstance(s, CaptureStep)), 0)
            self.acts = [
                a.model_copy(update={"game_ms": a.game_ms - start}) for a in recording.acts()
            ]
            self.captions = [
                Caption(
                    a.game_ms + a.used_ms,
                    recording.agents.get(e.slot, str(e.slot)),
                    str(e.data.get("message", "")),
                    frozenset([e.slot]),
                )
                for a in self.acts
                for e in a.events
                if e.type == "text_chat" and e.slot is not None
            ]
        self.cols = math.ceil(math.sqrt(len(self.slots)))
        self.rows = math.ceil(len(self.slots) / self.cols)
        width = self.cols * info.width
        height = HEADER_H + self.rows * info.height
        self.size = (width + width % 2, height + height % 2)
        self._last: dict[int, Image.Image] = {}

    # ------------------------------------------------------------ timeline

    def sequence(self) -> Iterator[VideoFrame]:
        """Capture frames in order, with a hold at each chat message."""
        says = sorted(c.game_ms for c in self.captions)
        i = 0
        last = max(self.info.frames - 1, 0)
        for k in range(self.info.frames):
            t = k * self.step_ms
            while i < len(says) and says[i] <= t:
                yield from self._hold(k, says[i])
                i += 1
            yield VideoFrame(k, t)
        for game_ms in says[i:]:
            yield from self._hold(last, game_ms)

    def _hold(self, index: int, game_ms: float) -> Iterator[VideoFrame]:
        for _ in range(self.hold_frames):
            yield VideoFrame(index, game_ms)

    def act_at(self, game_ms: float) -> ActStep | None:
        for act in self.acts:
            if act.game_ms <= game_ms < act.game_ms + max(act.used_ms, 1):
                return act
        return None

    def captions_at(self, slot: int, game_ms: float) -> list[Caption]:
        shown = [
            c
            for c in self.captions
            if slot in c.slots and c.game_ms <= game_ms < c.game_ms + self.caption_ms
        ]
        return shown[-self.max_captions :]

    # -------------------------------------------------------------- drawing

    def tile(self, slot: int, index: int) -> Image.Image:
        path = self.directory / f"slot{slot}" / f"{index:06d}.jpg"
        size = (self.info.width, self.info.height)
        if path.exists():
            with Image.open(path) as img:
                frame = img.convert("RGB")
            if frame.size != size:
                frame = frame.resize(size)
            self._last[slot] = frame
        return self._last.get(slot) or Image.new("RGB", size, IDLE)

    def render(self, frame: VideoFrame) -> Image.Image:
        out = Image.new("RGB", self.size, BACKGROUND)
        draw = ImageDraw.Draw(out)
        act = self.act_at(frame.game_ms)
        header = f"game time {frame.game_ms / 1000:6.1f} s"
        if act is not None:
            header = f"turn {act.turn + 1}   {self._name(act.slot)} acts   " + header
        draw.text((12, HEADER_H // 2), header, fill=TEXT, anchor="lm", font=_font(20))

        w, h = self.info.width, self.info.height
        for i, slot in enumerate(self.slots):
            x, y = (i % self.cols) * w, HEADER_H + (i // self.cols) * h
            out.paste(self.tile(slot, frame.index), (x, y))
            active = act is not None and act.slot == slot
            draw.rectangle(
                [x, y, x + w - 1, y + h - 1], outline=ACTIVE if active else IDLE, width=BORDER
            )
            self._label(draw, x + BORDER + 6, y + BORDER + 6, self._name(slot))
            self._captions(draw, x, y, self.captions_at(slot, frame.game_ms))
        return out

    def frames(self) -> Iterator[Image.Image]:
        for frame in self.sequence():
            yield self.render(frame)

    def _name(self, slot: int) -> str:
        return self.info.slots.get(slot, f"slot {slot}")

    def _label(self, draw: ImageDraw.ImageDraw, x: int, y: int, text: str) -> None:
        font = _font(18)
        box = draw.textbbox((x, y), text, font=font)
        draw.rectangle([box[0] - 4, box[1] - 3, box[2] + 4, box[3] + 3], fill=(0, 0, 0))
        draw.text((x, y), text, fill=TEXT, font=font)

    def _captions(self, draw: ImageDraw.ImageDraw, x: int, y: int, captions: list[Caption]) -> None:
        if not captions:
            return
        w, h = self.info.width, self.info.height
        size = max(12, w // 42)
        font = _font(size)
        chars = max(20, int((w - 40) / (size * 0.55)))
        lines: list[str] = []
        for c in captions:
            lines += textwrap.wrap(f"{c.speaker}: {c.text}", chars) or [""]
        line_h = size + 4
        lines = lines[-max(1, (h // 2) // line_h) :]
        top = y + h - BORDER - 8 - len(lines) * line_h
        draw.rectangle(
            [x + BORDER, top - 6, x + w - BORDER - 1, y + h - BORDER - 1], fill=(0, 0, 0)
        )
        for n, line in enumerate(lines):
            draw.text((x + BORDER + 10, top + n * line_h), line, fill=TEXT, font=font)


def find_ffmpeg() -> str | None:
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def write_mp4(composer: Composer, out: Path, ffmpeg: str) -> int:
    """Encode the composed frames with ffmpeg. Returns the number of frames."""
    w, h = composer.size
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(composer.info.fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "20",
        str(out),
    ]
    n = 0
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        assert proc.stdin is not None
        try:
            for image in composer.frames():
                proc.stdin.write(image.tobytes())
                n += 1
        finally:
            proc.stdin.close()
        stderr = proc.stderr.read().decode() if proc.stderr else ""
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {stderr.strip()}")
    return n


def write_jpegs(composer: Composer, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for n, image in enumerate(composer.frames(), 1):
        image.save(out / f"{n - 1:06d}.jpg", quality=90)
    return n


def save(composer: Composer, out: Path | None = None, jpegs: Path | None = None) -> str:
    """Write the video as mp4 (default: `<frame folder>/episode.mp4`), or as JPEGs to `jpegs`.

    Returns a line for the user. Raises `RuntimeError` if there is no ffmpeg for an mp4.
    """
    if jpegs is not None:
        n = write_jpegs(composer, jpegs)
        return f"wrote {n} frames to {jpegs}"
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg not found. Install it, run `uv sync --extra video`, or use --jpegs."
        )
    out = out or composer.directory / "episode.mp4"
    n = write_mp4(composer, out, ffmpeg)
    return f"wrote {out} ({n} frames, {n / composer.info.fps:.1f} s)"

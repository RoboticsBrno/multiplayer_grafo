import argparse
import asyncio
import dataclasses
import json
import logging
import os
import random
import re
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import pygame
import serial
from aiohttp import web

LOGGER = logging.getLogger(__name__)

CANVAS_RES_Y = 1024
CANVAS_RES_X = int(CANVAS_RES_Y * 1.33)

UPDATE_TIMEOUT_SECS = 1.0
UPDATE_TIMEOUT_SECS = 1000000.0
UPDATE_TICK_RATE_SECS = 0.05

MAX_SPEED = 0.06

COLORS = [
    (15, 68, 51),
    (14, 145, 230),
    (9, 194, 123),
    (6, 115, 171),
    (3, 245, 27),
    (2, 25, 111),
    (0, 58, 159),
    (0, 11, 205),
    (0, 9, 104),
    (4, 202, 245),
    (8, 188, 52),
    (12, 221, 195),
    (15, 254, 179),
    (15, 252, 16),
    (15, 249, 128),
    (15, 245, 114),
    (7, 149, 84),
    (6, 7, 216),
    (9, 233, 233),
]


class CanvasState(TypedDict):
    res_x: int
    res_y: int
    pointers: "List[PointerWebInfo]"


class PointerWebInfo(TypedDict):
    id: str
    x: float
    y: float
    dx: float
    dy: float
    clr: str
    th: float


@dataclass
class Pointer:
    last_update: float
    addr: str
    color: Tuple[int, int, int]
    x: float
    y: float
    delta_x: float
    delta_y: float
    thickness: float

    def info(self) -> PointerWebInfo:
        return {
            "id": self.addr,
            "x": self.x,
            "y": self.y,
            "dx": self.delta_x,
            "dy": self.delta_y,
            "clr": "#%02x%02x%02x" % self.color,
            "th": self.thickness,
        }

    def asdict(self) -> Dict[str, Any]:
        res = dataclasses.asdict(self)
        res["color"] = list(self.color)
        return res

    @staticmethod
    def fromdict(data: Dict[str, Any]) -> "Pointer":
        data["color"] = tuple(data["color"])
        res = Pointer(**data)
        return res


class SerialHandler(threading.Thread):
    CMD_SPEED_RE = re.compile(r"s ([0-9.-]+) ([0-9.-]+)")
    CMD_COLOR_RE = re.compile(r"c #([0-9a-fA-F]{6})")
    CMD_THICKNESS_RE = re.compile(r"t ([0-9]+)")

    def __init__(
        self, port: str, game: "Game", loop: asyncio.AbstractEventLoop
    ) -> None:
        super().__init__()
        self._port = port
        self._loop = loop
        self._game = game
        self._stop_ev = threading.Event()

    def stop(self) -> None:
        self._stop_ev.set()
        self.join()

    def run(self) -> None:
        try:
            with serial.Serial(self._port, baudrate=921600, timeout=0.2) as port:
                while not self._stop_ev.is_set():
                    line_bytes = port.readline()
                    if not line_bytes:
                        continue
                    line = line_bytes[:-1].decode("utf-8", errors="replace")

                    # 34851850816a 100 0
                    if len(line) < 13 or line[12] != " ":
                        continue

                    id = line[:12]
                    msg = line[13:]

                    try:
                        self._handle_command(id, msg)
                    except Exception:
                        continue
        except Exception as e:
            LOGGER.exception("serial failed")
            sys.exit(1)

    def _handle_command(self, id: str, cmd: str) -> None:
        if m := self.CMD_SPEED_RE.match(cmd):
            sx = float(m.group(1))
            sy = float(m.group(2))
            self._loop.call_soon_threadsafe(self._game.on_speed_received, id, sx, sy)
        elif m := self.CMD_COLOR_RE.match(cmd):
            clr = m.group(1)
            clr_rgb = (
                int(clr[0:2], base=16),
                int(clr[2:4], base=16),
                int(clr[4:6], base=16),
            )

            if all(c >= 0 and c <= 255 for c in clr_rgb):
                self._loop.call_soon_threadsafe(
                    self._game.on_color_received, id, clr_rgb
                )
        elif m := self.CMD_THICKNESS_RE.match(cmd):
            thickness = int(m.group(1))
            if thickness > 0.5 and thickness <= 10:
                self._loop.call_soon_threadsafe(
                    self._game.on_thickness_received, id, thickness
                )


class Game:
    BASE_IMAGE_NAME = "base.png"

    def __init__(self) -> None:
        self._pointers: Dict[str, Pointer] = {}
        self._surface = pygame.Surface((CANVAS_RES_X, CANVAS_RES_Y))
        self._surface.fill((255, 255, 255))

        self._db = self._init_db()
        self._last_save = time.time()
        self._load_state()

    def surface_png(self) -> bytes:
        res_bytes = BytesIO()
        pygame.image.save(self._surface, res_bytes, "base.png")
        return res_bytes.getvalue()

    def active_pointers(self) -> List[PointerWebInfo]:
        now = time.time()
        return [
            p.info()
            for p in self._pointers.values()
            if now - p.last_update <= UPDATE_TIMEOUT_SECS
        ]

    def on_speed_received(self, id: str, sx: float, sy: float) -> None:
        pntr = self._get_pntr(id)
        pntr.delta_x = sx / 100 * MAX_SPEED
        pntr.delta_y = sy / 100 * MAX_SPEED

    def on_color_received(self, id: str, color: Tuple[int, int, int]) -> None:
        pntr = self._get_pntr(id)
        pntr.color = color

    def on_thickness_received(self, id: str, thickness: int) -> None:
        pntr = self._get_pntr(id)
        pntr.thickness = thickness

    def _get_pntr(self, id: str) -> Pointer:
        pntr = self._pointers.get(id)
        if pntr is None:
            pntr = Pointer(
                time.time(),
                id,
                self._generate_color(id),
                CANVAS_RES_X / 2,
                CANVAS_RES_Y / 2,
                0,
                0,
                2,
            )
            self._pointers[id] = pntr
            print(f"New pointer {id}, now got {len(self._pointers)}")
        else:
            pntr.last_update = time.time()
        return pntr

    async def run(self) -> None:
        last_tm = time.time()
        while True:
            now = time.time()
            diff_ms = int((now - last_tm) * 1000)
            last_tm = now

            for p in self._pointers.values():
                if now - p.last_update > UPDATE_TIMEOUT_SECS:
                    continue

                new_x = self._clamp_x(p.x + p.delta_x * diff_ms)
                new_y = self._clamp_y(p.y + p.delta_y * diff_ms)

                pygame.draw.line(
                    self._surface,
                    p.color,
                    (p.x, p.y),
                    (new_x, new_y),
                    round(p.thickness),
                )
                p.x = new_x
                p.y = new_y

            await asyncio.sleep(UPDATE_TICK_RATE_SECS)

    def _save_state(self) -> None:
        changed_pointers = [
            p for p in self._pointers.values() if p.last_update > self._last_save
        ]

        if not changed_pointers:
            return

        base_img = self.surface_png()

        print("Saving game state")
        cur = self._db.cursor()
        cur.execute("BEGIN;")
        try:
            for p in changed_pointers:
                print(json.dumps(p.asdict()))
                cur.execute(
                    """INSERT INTO pointers (addr, last_update, data) VALUES (?, ?, ?)
                    ON CONFLICT(addr) DO UPDATE SET last_update=excluded.last_update, data=excluded.data;""",
                    (p.addr, p.last_update, json.dumps(p.asdict())),
                )
            cur.execute(
                "INSERT INTO images (name, data_png) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET data_png=excluded.data_png",
                (self.BASE_IMAGE_NAME, base_img),
            )
            cur.execute("COMMIT;")
            self._last_save = time.time()
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.close()

    def _load_state(self) -> None:
        cur = self._db.cursor()
        for row in cur.execute("SELECT data FROM pointers"):
            try:
                pntr = Pointer.fromdict(json.loads(row[0]))
                self._pointers[pntr.addr] = pntr
            except Exception:
                LOGGER.exception("failed to deserialize pointer, skipping")
                continue

        cur.execute(
            "SELECT data_png FROM images WHERE name=?;", (self.BASE_IMAGE_NAME,)
        )
        base_img_data = cur.fetchone()
        if base_img_data is not None:
            base_img = BytesIO(base_img_data[0])
            self._surface = pygame.transform.scale(
                pygame.image.load(base_img, "base.png"), (CANVAS_RES_X, CANVAS_RES_Y)
            )

    @staticmethod
    def _init_db() -> sqlite3.Connection:
        con = sqlite3.connect("state.sqlite3", isolation_level=None)
        con.execute("pragma journal_mode=wal")
        con.executescript(
            """
        BEGIN;
        CREATE TABLE IF NOT EXISTS pointers(
            addr TEXT NOT NULL,
            last_update REAL NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY(addr)
        );
        CREATE TABLE IF NOT EXISTS images(
            name TEXT NOT NULL,
            data_png BLOB NOT NULL,
            PRIMARY KEY(name)
        );
        COMMIT;
        """
        )
        return con

    @staticmethod
    def _generate_color(id: str) -> Tuple[int, int, int]:
        try:
            addr_as_int = int(id[4:])
            return COLORS[addr_as_int % len(COLORS)]
        except ValueError:
            return COLORS[random.randint(0, len(COLORS) - 1)]

    @staticmethod
    def _clamp_x(x: float) -> float:
        if x < 0:
            return 0
        elif x > CANVAS_RES_X:
            return CANVAS_RES_X
        return x

    @staticmethod
    def _clamp_y(y: float) -> float:
        if y < 0:
            return 0
        elif y > CANVAS_RES_Y:
            return CANVAS_RES_Y
        return y


class WebServer:
    def __init__(self, game: Game) -> None:
        self._game = game

    async def start(self, port: int) -> None:
        app = web.Application()

        app.add_routes(
            [
                web.get("/", self.handle_index),
                web.get("/base.png", self.handle_base_png),
                web.get("/pointers.json", self.handle_pointers_json),
            ]
        )

        print("Starting web server at 0.0.0.0:%d" % port)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

    async def handle_index(self, _req: web.Request) -> web.StreamResponse:
        src_root = str(Path(__file__).absolute())
        return web.FileResponse(os.path.join(os.path.dirname(src_root), "index.html"))

    async def handle_base_png(self, _req: web.Request) -> web.Response:
        return web.Response(body=self._game.surface_png(), content_type="image/png")

    async def handle_pointers_json(self, _req: web.Request) -> web.Response:
        res: CanvasState = {
            "res_x": CANVAS_RES_X,
            "res_y": CANVAS_RES_Y,
            "pointers": self._game.active_pointers(),
        }
        return web.json_response(res)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-wp", "--web-port", default=8245, type=int)
    parser.add_argument("-p", "--port", default="/dev/ttyUSB0")

    args = parser.parse_args()

    game = Game()
    server = WebServer(game)

    serial_handler = SerialHandler(args.port, game, asyncio.get_running_loop())
    serial_handler.start()

    await server.start(args.web_port)

    try:
        await game.run()
    finally:
        serial_handler.stop()
        game._save_state()


if __name__ == "__main__":
    asyncio.run(main())

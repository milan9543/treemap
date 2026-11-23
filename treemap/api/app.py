"""The ``/api/v2`` endpoints of ``treemap serve``.

The server drives any number of **devices**: WLED controllers added on its page by
address (see :mod:`treemap.devices`). It starts with none, needs none configured, and
keeps running while they're off. Each device has its own LEDs, map, scans, effects and
test patterns, under ``/devices/{id}`` (see :mod:`treemap.api.device`); favourites and
playlists are shared by all.

======  ======================  ========================================================
GET     /info                   API and server version, the server's address on the
                                LAN (``url``) and the scan page's (``scan_page``), for
                                QR codes
GET     /devices                ``{"devices": [...]}``, each as ``GET /devices/{id}``
POST    /devices                ``{"host", "name"?, "led_count"?}``: add a controller.
                                Its LED count (and name) is read from its WLED; one
                                that doesn't answer yet is added without, unless given
GET     /devices/{id}           the device: ``id``, ``name``, ``host``, ``virtual``,
                                ``status`` (``alive``, ``checked_s_ago``, ``wled``: its
                                name, version and LED count, ``error``), and once its
                                LED count is known everything its LEDs are doing
PUT     /devices/{id}           ``{"name"?, "led_count"?}``: rename it, or take WLED's
                                LED count after it changed (its map must then be scanned
                                again)
DELETE  /devices/{id}           take it off the list (its map and scans stay on disk)
...     /devices/{id}/...       the device's own endpoints: :mod:`treemap.api.device`
GET     /effects                the effects to pick from, with their parameters (name,
                                kind, default, range, choices) to build controls from;
                                ``needs_map``: it places light by the mapped positions
GET     /favourites             ``{"favourites": [...]}`` (see :mod:`treemap.library`)
POST    /favourites             ``{"name", "effect", "params"}``: keep a favourite
PUT     /favourites/{id}        ``{"name"?, "params"?}``: rename it, or new settings
DELETE  /favourites/{id}        delete it (and take it out of every playlist)
GET     /playlists              ``{"playlists": [...]}``
POST    /playlists              ``{"name", "items", "crossfade_s", "shuffle"}``
PUT     /playlists/{id}         replace a playlist's name, items, crossfade and shuffle
DELETE  /playlists/{id}         delete it
======  ======================  ========================================================

A device whose controller has never answered has no LED count yet, so it has none of its
own endpoints (they answer 409) until it does: the status check reads it then.
"""

from __future__ import annotations

import copy
import logging
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from treemap import __version__
from treemap.api.device import DeviceApi
from treemap.api.http import HttpError, Request, Router
from treemap.config import Config
from treemap.devices import (
    MAX_DEVICES,
    MAX_LEDS,
    VIRTUAL_PRODUCT,
    DeviceError,
    DeviceOutput,
    DeviceRecord,
    DeviceStore,
    normalise_host,
    probe,
    wled_led_count,
)
from treemap.effects import describe_effects
from treemap.library import Library, LibraryError
from treemap.outputs.base import LedOutput

log = logging.getLogger(__name__)

API_VERSION = 2
PREFIX = "/api/v2"
CHECK_S = 5.0  # how often each controller is asked whether it's there

# Opens a device's LEDs on its controller; tests swap in a recorder.
OpenLeds = Callable[[DeviceRecord, Config], LedOutput]


def open_wled(record: DeviceRecord, cfg: Config) -> LedOutput:
    from treemap.outputs.wled import Controller, WledOutput

    return WledOutput(cfg.led_count, [Controller(record.host, 0, cfg.led_count)])


class Device:
    """A device on the list: its record, whether it answers, and (once its LED count is
    known) its :class:`DeviceApi`."""

    def __init__(self, record: DeviceRecord) -> None:
        self.record = record
        self.api: DeviceApi | None = None
        self.alive: bool | None = None  # None: not asked yet
        self.checked_at = 0.0
        self.wled: dict[str, Any] | None = None  # its name, version and LED count
        self.error: str | None = None

    def status(self) -> dict[str, Any]:
        return {"alive": self.alive,
                "checked_s_ago": round(time.monotonic() - self.checked_at, 1)
                if self.checked_at else None,
                "wled": self.wled, "error": self.error}


class Api:
    def __init__(self, cfg: Config, open_leds: OpenLeds = open_wled, url: str | None = None,
                 check_s: float = CHECK_S) -> None:
        self.cfg = cfg
        self.open_leds = open_leds
        self.url = url  # the server's address on the LAN
        self.library = Library(cfg.library_path, MAX_LEDS)
        self.store = DeviceStore(cfg.resolve("data/devices.json"))
        self._lock = threading.RLock()
        self.devices: dict[str, Device] = {}
        for record in self.store.load():
            self.devices[record.id] = device = Device(record)
            self._start(device)
        self._stop = threading.Event()
        self._checker = threading.Thread(target=self._check_loop, args=(check_s,),
                                         name="device-check", daemon=True)
        self._checker.start()

        self.router = Router()
        for method, path, handler in (
            ("GET", "/info", self.info),
            ("GET", "/devices", self.list_devices),
            ("POST", "/devices", self.add_device),
            ("GET", "/devices/{id}", self.get_device),
            ("PUT", "/devices/{id}", self.put_device),
            ("DELETE", "/devices/{id}", self.delete_device),
            ("GET", "/effects", self.effects),
            ("GET", "/favourites", self.favourites),
            ("POST", "/favourites", self.add_favourite),
            ("PUT", "/favourites/{id}", self.put_favourite),
            ("DELETE", "/favourites/{id}", self.delete_favourite),
            ("GET", "/playlists", self.playlists),
            ("POST", "/playlists", self.add_playlist),
            ("PUT", "/playlists/{id}", self.put_playlist),
            ("DELETE", "/playlists/{id}", self.delete_playlist),
        ):
            self.router.add(method, PREFIX + path, handler)
        for method, path, name in DeviceApi.ROUTES:
            self.router.add(method, PREFIX + "/devices/{id}" + path, self._on_device(name))

    # -- devices ------------------------------------------------------------------------

    def _device_config(self, record: DeviceRecord) -> Config:
        """The server's config, for this device's LEDs and with its own data folder."""
        cfg = copy.copy(self.cfg)
        cfg.led_count = record.led_count
        cfg.device_dir = self.cfg.resolve("data") / "devices" / record.id
        if record.virtual:
            cfg.engine = copy.copy(cfg.engine)
            cfg.engine.gamma = 1.0  # a screen: it applies its own gamma
        return cfg

    def _start(self, device: Device) -> None:
        """Give the device its LEDs, engine and scans, once its LED count is known."""
        record = device.record
        if record.led_count is None or device.api is not None:
            return
        cfg = self._device_config(record)
        output = DeviceOutput(record.led_count, lambda: self.open_leds(record, cfg))
        device.api = DeviceApi(record, cfg, output, self.library,
                               legacy_dir=self.cfg.resolve("data"))

    def _device(self, req: Request) -> Device:
        device = self.devices.get(req.args["id"])
        if device is None:
            raise HttpError(404, f"there's no device {req.args['id']!r}")
        return device

    def _on_device(self, name: str) -> Callable[[Request], Any]:
        def handler(req: Request) -> Any:
            device = self._device(req)
            if device.api is None:
                raise HttpError(409, f"{device.record.name} hasn't answered yet, so its LED "
                                     "count isn't known: switch it on")
            return getattr(device.api, name)(req)
        return handler

    def _describe(self, device: Device) -> dict[str, Any]:
        r = device.record
        out = {"id": r.id, "name": r.name, "host": r.host, "virtual": r.virtual,
               "led_count": r.led_count, "status": device.status()}
        if device.api is not None:
            out.update(device.api.summary())
            out["error"] = device.api.output.error
        return out

    def list_devices(self, req: Request) -> dict[str, Any]:
        return {"devices": [self._describe(d) for d in list(self.devices.values())]}

    def get_device(self, req: Request) -> dict[str, Any]:
        return self._describe(self._device(req))

    def add_device(self, req: Request) -> tuple[int, dict[str, Any]]:
        body = req.json()
        unknown = set(body) - {"host", "name", "led_count"}
        if unknown:
            raise HttpError(400, f"unknown field(s): {', '.join(sorted(unknown))}")
        try:
            host = normalise_host(body.get("host"))
            name = _name(body.get("name"))
            count = _led_count(body.get("led_count"))
        except DeviceError as e:
            raise HttpError(400, str(e)) from None
        with self._lock:
            if any(d.record.host == host for d in self.devices.values()):
                raise HttpError(409, f"{host} is on the list already")
            if len(self.devices) >= MAX_DEVICES:
                raise HttpError(409, f"there are {MAX_DEVICES} devices already")
        device = Device(DeviceRecord(id="", name=name or host, host=host, led_count=count))
        self._check(device)  # reads its LED count, name and whether it's virtual
        if device.wled is not None and not name:
            device.record.name = device.wled["name"] or host
        with self._lock:
            device.record.id = DeviceStore.new_id(set(self.devices))
            self.devices[device.record.id] = device
            self._save()
            self._start(device)
        return 201, self._describe(device)

    def put_device(self, req: Request) -> dict[str, Any]:
        device = self._device(req)
        body = req.json()
        unknown = set(body) - {"name", "led_count"}
        if unknown:
            raise HttpError(400, f"unknown field(s): {', '.join(sorted(unknown))}")
        try:
            name = _name(body.get("name")) if "name" in body else None
            count = _led_count(body.get("led_count")) if "led_count" in body else None
        except DeviceError as e:
            raise HttpError(400, str(e)) from None
        with self._lock:
            if name:
                device.record.name = name
            if count is not None and count != device.record.led_count:
                if device.api is not None and device.api.jobs.busy:
                    raise HttpError(409, "a scan is running on it; stop it first")
                self._close(device)
                device.record.led_count = count
                self._start(device)
            self._save()
        return self._describe(device)

    def delete_device(self, req: Request) -> dict[str, Any]:
        device = self._device(req)
        with self._lock:
            self.devices.pop(device.record.id, None)
            self._save()
        self._close(device)
        return {"deleted": device.record.id}

    def _save(self) -> None:
        self.store.save([d.record for d in self.devices.values()])

    @staticmethod
    def _close(device: Device) -> None:
        api, device.api = device.api, None
        if api is not None:
            api.close()

    # -- is it there? -------------------------------------------------------------------

    def _check(self, device: Device) -> None:
        """Ask the controller for its WLED info: is it there, how many LEDs, is it the
        virtual one. A device without an LED count takes WLED's."""
        try:
            info = probe(device.record.host)
            count = wled_led_count(info)
        except (OSError, ValueError) as e:
            device.alive, device.error = False, _reason(e)
        else:
            device.alive, device.error = True, None
            device.wled = {"name": str(info.get("name") or ""), "version": info.get("ver"),
                           "led_count": count}
            virtual = info.get("product") == VIRTUAL_PRODUCT
            if device.record.led_count is None or device.record.virtual != virtual:
                device.record.virtual = virtual
                if device.record.led_count is None:
                    device.record.led_count = count
                with self._lock:
                    if device.record.id in self.devices:
                        self._save()
                        self._start(device)
        device.checked_at = time.monotonic()

    def _check_loop(self, every_s: float) -> None:
        while True:
            threads = [threading.Thread(target=self._check, args=(d,), daemon=True)
                       for d in list(self.devices.values())]
            for t in threads:
                t.start()
            for t in threads:
                t.join(every_s)
            if self._stop.wait(every_s):
                return

    # -- global endpoints ---------------------------------------------------------------

    def info(self, req: Request) -> dict[str, Any]:
        return {"api": API_VERSION, "server": f"treemap {__version__}", "url": self.url,
                "scan_page": self.cfg.server.scan_page, "devices": len(self.devices)}

    def effects(self, req: Request) -> dict[str, Any]:
        return {"effects": describe_effects(MAX_LEDS)}

    def _library(self, change: Callable[[], Any]) -> Any:
        try:
            return change()
        except KeyError as e:
            raise HttpError(404, e.args[0] if e.args else "not found") from None
        except LibraryError as e:
            raise HttpError(400, str(e)) from None

    def favourites(self, req: Request) -> dict[str, Any]:
        return {"favourites": self.library.favourites()}

    def add_favourite(self, req: Request) -> tuple[int, dict[str, Any]]:
        return 201, self._library(lambda: self.library.add_favourite(req.json()))

    def put_favourite(self, req: Request) -> dict[str, Any]:
        return self._library(lambda: self.library.update_favourite(req.args["id"], req.json()))

    def delete_favourite(self, req: Request) -> dict[str, Any]:
        self._library(lambda: self.library.remove_favourite(req.args["id"]))
        return {"deleted": req.args["id"]}

    def playlists(self, req: Request) -> dict[str, Any]:
        return {"playlists": self.library.playlists()}

    def add_playlist(self, req: Request) -> tuple[int, dict[str, Any]]:
        return 201, self._library(lambda: self.library.add_playlist(req.json()))

    def put_playlist(self, req: Request) -> dict[str, Any]:
        return self._library(lambda: self.library.put_playlist(req.args["id"], req.json()))

    def delete_playlist(self, req: Request) -> dict[str, Any]:
        self._library(lambda: self.library.remove_playlist(req.args["id"]))
        return {"deleted": req.args["id"]}

    # -- lifecycle ----------------------------------------------------------------------

    def close(self) -> None:
        """Stop every device's scan (keeping finished rounds), effect and test pattern,
        and turn its LEDs off."""
        self._stop.set()
        for device in list(self.devices.values()):
            self._close(device)


def _name(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > 60:
        raise DeviceError("name must be text, up to 60 characters")
    return value.strip() or None


def _led_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LEDS:
        raise DeviceError(f"led_count must be a whole number 1-{MAX_LEDS}")
    return value


def _reason(e: Exception) -> str:
    reason = getattr(e, "reason", None)  # urllib wraps the socket's error
    text = str(reason if reason is not None else e)
    if isinstance(reason, socket.timeout) or "timed out" in text:
        return "no answer"
    if isinstance(reason, socket.gaierror):
        return "the name doesn't resolve"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    return text


def lan_address() -> str:
    """This machine's address on the LAN (the interface with the default route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # sends nothing; just picks the interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

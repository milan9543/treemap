"""``treemap serve``: the server that drives the devices, its page, and the HTTP API the
page and the phone's scan page use.

:mod:`treemap.api.app` has the server's endpoints and the device list,
:mod:`treemap.api.device` each device's, :mod:`treemap.api.http` the HTTP and CORS
plumbing, :mod:`treemap.api.leds` the test patterns.
"""

from treemap.api.app import API_VERSION, Api, lan_address
from treemap.api.http import HttpServer

__all__ = ["API_VERSION", "Api", "HttpServer", "lan_address"]

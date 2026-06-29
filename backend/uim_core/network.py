from __future__ import annotations

import os
import urllib.request


def configured_network_proxy() -> str:
    return (
        os.environ.get("UIM_NETWORK_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    ).strip()


def set_network_proxy(value: str) -> None:
    proxy = value.strip()
    if proxy:
        os.environ["UIM_NETWORK_PROXY"] = proxy
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[key] = proxy
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        return

    os.environ.pop("UIM_NETWORK_PROXY", None)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)


def open_external_url(request: urllib.request.Request, timeout: float):
    proxy = configured_network_proxy()
    if not proxy:
        return urllib.request.urlopen(request, timeout=timeout)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(
            {
                "http": proxy,
                "https": proxy,
            }
        )
    )
    return opener.open(request, timeout=timeout)

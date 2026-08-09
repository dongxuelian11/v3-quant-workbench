
from __future__ import annotations

import re
from dataclasses import dataclass


class VersionCompatibilityError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class ApiVersion:
    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, value: str) -> "ApiVersion":
        match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?", value)
        if match is None:
            raise VersionCompatibilityError(f"invalid API version: {value!r}")
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))

    @property
    def major_minor(self) -> str:
        return f"{self.major}.{self.minor}"


WIRE_API_VERSION = ApiVersion(1, 0, 0)


def ensure_wire_compatible(expected: str, offered: str = "1.0") -> ApiVersion:
    client = ApiVersion.parse(expected)
    server = ApiVersion.parse(offered)
    if client.major != server.major:
        raise VersionCompatibilityError(
            f"incompatible contract major: client={client.major}, server={server.major}"
        )
    if client.minor > server.minor:
        raise VersionCompatibilityError(
            f"unsupported contract minor: client={client.minor}, server={server.minor}"
        )
    return ApiVersion(server.major, client.minor, 0)

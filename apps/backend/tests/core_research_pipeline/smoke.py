from __future__ import annotations

import json

from .helpers import build_pipeline_development_fixture


def main() -> int:
    fixture = build_pipeline_development_fixture()
    try:
        result = fixture.service.run(fixture.request)
        print(json.dumps(result.to_wire(), sort_keys=True, ensure_ascii=False))
        return 0 if result.succeeded else 1
    finally:
        fixture.close()


if __name__ == "__main__":
    raise SystemExit(main())

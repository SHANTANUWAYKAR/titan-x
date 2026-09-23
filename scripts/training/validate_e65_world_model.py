"""Live sanity check for E65 World Model -- runs a real build_world_view()
composing E04/E10/E19/E64's own real outputs. No calibration (Rule 3):
pure composition."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.registry import get_registry

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e65_world_model" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    reg = get_registry()
    engine = reg.get("e65_world_model")
    result = engine.build_world_view()
    logger.info(result.message)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": result.data.to_dict() if result.data else None}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json

from .research_fixture import build_alpha_research_fixture


def main() -> None:
    fixture = build_alpha_research_fixture()
    try:
        result = fixture.service.run(fixture.job)
        payload = {
            "job_spec_id": result.job_spec_id,
            "run_id": result.mining_run.alpha_mining_run_id,
            "dataset_version_id": result.dataset_version_id,
            "dataset_resolution_receipt_id": result.dataset_resolution_receipt.receipt_identity,
            "generations": result.generation_count,
            "generated": result.mining_run.generated_count,
            "evaluated": result.mining_run.evaluated_count,
            "rejected": result.mining_run.rejected_count,
            "rewarded": result.rewarded_count,
            "best_candidate": result.best_factor_definition_version_id,
            "best_reward": result.best_reward,
            "result_artifact_id": result.result_artifact.artifact_id,
            "status": result.mining_run.status.value,
            "truth": "PRE_ALPHA / RESEARCH_ONLY",
            "maturity": result.maturity,
            "product_connected": result.product_connected,
            "production_available": result.production_available,
        }
        if (
            payload["generations"] < 2
            or payload["evaluated"] < 2
            or payload["rewarded"] < 1
        ):
            raise RuntimeError("bounded Alpha research smoke acceptance counts were not met")
        print("ALPHA_RESEARCH_SMOKE=" + json.dumps(payload, sort_keys=True))
    finally:
        fixture.close()


if __name__ == "__main__":
    main()

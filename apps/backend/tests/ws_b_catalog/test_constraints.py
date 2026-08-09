from __future__ import annotations

import sqlite3

from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.errors.exceptions import InvalidArgumentError

from .support import NOW, CatalogTestCase


class ConstraintTests(CatalogTestCase):
    def test_published_artifact_reachability_is_enforced_by_schema(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with SQLiteUnitOfWork(self.connection):
                self.connection.execute(
                    """
                    INSERT INTO artifact_reference(
                      artifact_reference_id,owner_type,owner_id,role,artifact_id,state,created_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        "arf_orphan",
                        "PROJECT",
                        "prj_none",
                        "EVIDENCE",
                        "art_sha256_" + "f" * 64,
                        "ACTIVE",
                        NOW,
                    ),
                )

    def test_foreign_keys_are_enabled(self) -> None:
        self.assertEqual(self.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            with SQLiteUnitOfWork(self.connection):
                self.connection.execute(
                    """
                    INSERT INTO task(
                      task_id,project_id,service_name,operation_id,task_type,display_name,
                      truth_state,state,created_by,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "tsk_orphan",
                        "prj_missing",
                        "TaskService",
                        "task.create",
                        "TEST",
                        "orphan",
                        "FORMAL",
                        "QUEUED",
                        "test",
                        NOW,
                        NOW,
                    ),
                )

    def test_published_version_is_immutable(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            self.add_project(repositories)
            artifact = self.publish_artifact(repositories)
            repositories.factor.table("factor_definition").add_new(
                {
                    "factor_definition_id": "fad_test",
                    "project_id": "prj_test",
                    "stable_name": "factor",
                    "definition_json": {"expression": "close"},
                    "created_at": NOW,
                }
            )
            repositories.factor.publish_version(
                "factor_version",
                {
                    "factor_version_id": "fav_test",
                    "factor_definition_id": "fad_test",
                    "semantic_version": "1.0.0",
                    "code_artifact_id": artifact["artifact_id"],
                    "code_hash": "d" * 64,
                    "availability_policy_json": {"cutoff": "EOD"},
                    "state": "PUBLISHED",
                    "published_at": NOW,
                },
            )
        with self.assertRaises(sqlite3.IntegrityError):
            with SQLiteUnitOfWork(self.connection):
                self.connection.execute(
                    "UPDATE factor_version SET code_hash=? WHERE factor_version_id='fav_test'",
                    ("e" * 64,),
                )

    def test_non_optimal_solution_cannot_bind_weights(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            with self.assertRaises(InvalidArgumentError):
                repositories.optimization.publish_solution(
                    {
                        "optimization_solution_id": "ops_test",
                        "optimization_problem_id": "opb_missing",
                        "solver_profile_id": "solver",
                        "status": "INFEASIBLE",
                        "weights_artifact_id": "art_sha256_" + "a" * 64,
                        "objective_value_decimal": "0",
                        "created_at": NOW,
                    }
                )
            with self.assertRaises(InvalidArgumentError):
                repositories.optimization.publish_solution(
                    {
                        "optimization_solution_id": "ops_optimal",
                        "optimization_problem_id": "opb_missing",
                        "solver_profile_id": "solver",
                        "status": "OPTIMAL",
                        "weights_artifact_id": "art_sha256_" + "a" * 64,
                        "residual_validation_artifact_id": "art_sha256_" + "b" * 64,
                        "objective_value_decimal": "1",
                        "created_at": NOW,
                    }
                )

    def test_valid_result_requires_independent_reconciliation_pass(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            with self.assertRaises(InvalidArgumentError):
                repositories.result.publish_result(
                    {
                        "result_id": "res_test",
                        "project_id": "prj_missing",
                        "backtest_run_id": "brs_missing",
                        "ledger_manifest_artifact_id": "art_sha256_" + "a" * 64,
                        "reconciliation_artifact_id": "art_sha256_" + "b" * 64,
                        "state": "VALID",
                        "lineage_hash": "c" * 64,
                        "created_at": NOW,
                    }
                )

from __future__ import annotations

import unittest

from v3_backend.domain.strategies import (
    BindingInputRef,
    BindingSlot,
    ComponentDescriptor,
    ComponentRegistry,
    ComponentRole,
    MissingSemantics,
    NodeOutputRef,
    ParameterKind,
    ParameterSpec,
    PortCardinality,
    PortSpec,
    PortValueType,
    StrategyCompiler,
    StrategyCycleError,
    StrategyIr,
    StrategyNode,
    StrategyPortError,
    default_component_registry,
)
from v3_backend.provenance.canonical_hash import canonical_json

from .helpers import build_strategy_ir, score_port


class StrategyIrCompilationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_component_registry()
        self.compiler = StrategyCompiler(self.registry)

    def test_canonical_ir_is_deterministic_and_projection_safe(self) -> None:
        normal = build_strategy_ir(projection_tag="normal")
        reversed_ir = build_strategy_ir(
            node_order=tuple(reversed(tuple(node.node_id for node in normal.nodes))),
            projection_tag="moved-and-reformatted",
            explicit_defaults=True,
        )
        first = self.compiler.compile(normal)
        second = self.compiler.compile(reversed_ir)
        self.assertEqual(first.canonical_ir_sha256, second.canonical_ir_sha256)
        self.assertEqual(
            first.strategy_definition_version_id,
            second.strategy_definition_version_id,
        )
        encoded = canonical_json(first.canonical_ir)
        self.assertNotIn("position", encoded)
        self.assertNotIn("viewport", encoded)
        self.assertNotIn("formatting", encoded)

    def test_cycle_is_rejected(self) -> None:
        nodes = (
            StrategyNode(
                "input.scores",
                "v3.strategy.input.bound_scores",
                "1.0.0",
                {"artifact": BindingInputRef("scores")},
                {},
            ),
            StrategyNode(
                "combine.a",
                "v3.strategy.combine.priority",
                "1.0.0",
                {
                    "primary": NodeOutputRef("combine.b", "scores"),
                    "fallback": NodeOutputRef("input.scores", "scores"),
                },
                {},
            ),
            StrategyNode(
                "combine.b",
                "v3.strategy.combine.priority",
                "1.0.0",
                {
                    "primary": NodeOutputRef("combine.a", "scores"),
                    "fallback": NodeOutputRef("input.scores", "scores"),
                },
                {},
            ),
            StrategyNode(
                "output.signal",
                "v3.strategy.output.signal",
                "1.0.0",
                {"scores": NodeOutputRef("combine.a", "scores")},
                {},
            ),
        )
        ir = StrategyIr(
            required_bindings=(
                BindingSlot("scores", "FEATURE_MATERIALIZATION", score_port()),
            ),
            nodes=nodes,
            outputs={"signal": NodeOutputRef("output.signal", "artifact")},
        )
        with self.assertRaises(StrategyCycleError):
            self.compiler.compile(ir)

    def test_dangling_binding_is_rejected(self) -> None:
        ir = StrategyIr(
            required_bindings=(
                BindingSlot("scores", "FEATURE_MATERIALIZATION", score_port()),
            ),
            nodes=(
                StrategyNode(
                    "input.scores",
                    "v3.strategy.input.bound_scores",
                    "1.0.0",
                    {"artifact": BindingInputRef("latest")},
                    {},
                ),
                StrategyNode(
                    "output.signal",
                    "v3.strategy.output.signal",
                    "1.0.0",
                    {"scores": NodeOutputRef("input.scores", "scores")},
                    {},
                ),
            ),
            outputs={"signal": NodeOutputRef("output.signal", "artifact")},
        )
        with self.assertRaisesRegex(StrategyPortError, "dangling binding"):
            self.compiler.compile(ir)

    def test_incompatible_port_is_rejected(self) -> None:
        base = build_strategy_ir()
        nodes = tuple(
            StrategyNode(
                node.node_id,
                node.component_type,
                node.component_version,
                (
                    {"scores": NodeOutputRef("select.top2", "selection")}
                    if node.node_id == "output.signal"
                    else node.inputs
                ),
                node.parameters,
                node.display_metadata,
            )
            for node in base.nodes
        )
        with self.assertRaisesRegex(StrategyPortError, "incompatible port type"):
            self.compiler.compile(
                StrategyIr(base.required_bindings, nodes, base.outputs)
            )

    def test_default_or_registry_semantics_change_definition_identity(self) -> None:
        score = score_port()
        artifact_port = PortSpec(
            PortValueType.SIGNAL_ARTIFACT,
            PortCardinality.ARTIFACT,
            "BOUND_DECISION_TIME",
            "BOUND_UNIVERSE_MEMBERSHIP",
            MissingSemantics.EXPLICIT,
        )

        def registry(default: str) -> ComponentRegistry:
            return ComponentRegistry(
                (
                    ComponentDescriptor(
                        "v3.strategy.input.bound_scores",
                        "1.0.0",
                        ComponentRole.INPUT_REFERENCE,
                        {"artifact": score},
                        {"scores": score},
                        (),
                        MissingSemantics.EXPLICIT,
                        0,
                        0,
                        True,
                        ("EXACT_INPUT_ARTIFACTS",),
                        "NO_CONFLICT",
                    ),
                    ComponentDescriptor(
                        "v3.strategy.output.signal",
                        "1.0.0",
                        ComponentRole.SIGNAL_OUTPUT,
                        {"scores": score},
                        {"artifact": artifact_port},
                        (
                            ParameterSpec(
                                "signal_kind",
                                ParameterKind.ENUM,
                                default,
                                allowed_values=("SCORE", "DIRECTIONAL_SCORE"),
                            ),
                        ),
                        MissingSemantics.EXPLICIT,
                        0,
                        0,
                        True,
                        ("EXACT_INPUT_ARTIFACTS",),
                        "ONE_ROW_PER_BOUND_INSTRUMENT",
                    ),
                )
            )

        ir = StrategyIr(
            required_bindings=(
                BindingSlot("scores", "FEATURE_MATERIALIZATION", score),
            ),
            nodes=(
                StrategyNode(
                    "input.scores",
                    "v3.strategy.input.bound_scores",
                    "1.0.0",
                    {"artifact": BindingInputRef("scores")},
                    {},
                ),
                StrategyNode(
                    "output.signal",
                    "v3.strategy.output.signal",
                    "1.0.0",
                    {"scores": NodeOutputRef("input.scores", "scores")},
                    {},
                ),
            ),
            outputs={"signal": NodeOutputRef("output.signal", "artifact")},
        )
        first = StrategyCompiler(registry("SCORE")).compile(ir)
        second = StrategyCompiler(registry("DIRECTIONAL_SCORE")).compile(ir)
        self.assertNotEqual(
            first.strategy_definition_version_id,
            second.strategy_definition_version_id,
        )

    def test_definition_identity_excludes_concrete_evaluation_inputs(self) -> None:
        definition = self.compiler.compile(build_strategy_ir())
        payload = canonical_json(definition.to_wire())
        for forbidden in (
            "snapshot-1",
            "universe-1",
            "calendar-1",
            "dataset_version_id",
            "knowledge_cutoff",
            "evaluation period",
        ):
            self.assertNotIn(forbidden, payload)
        with self.assertRaises(TypeError):
            definition.canonical_ir["nodes"][0]["parameters"]["forbidden"] = True  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()

"""ProductEntryService ASL contract: canonical research entry operations.

Bounded, versioned, non-P0 contract expansion for V1 Product Entry.  Existing
1.0 operations retain their exact wire contracts; additive V1.1 operations
are independently versioned under the same stable service namespace.
All operations are project-scoped;
projectless bootstrap (createProject / listProjects) is a separate narrow
runtime control protocol (see runtime/product_entry.py) and is deliberately
NOT an ASL operation because every ASL request envelope is project-bound by
frozen design.

listBacktestRunSpecs discovers durable, project-owned canonical BacktestRunSpec
references and verifies actual artifact bytes before listing them executable.

importResearchPackage imports an explicitly user-selected V3 research package
(closed manifest + actual payload bytes) only after every source/owner row and
payload independently matches canonical state that already exists in the
target runtime. Package-provided rows cannot bootstrap authority.
"""

from __future__ import annotations

from .common.dto import ClosedDto, ContractValidationError, validate_schema
from .common.operation import OperationContract, OperationKind, ServiceContract
from v3_backend.transport_contract import (
    MAX_PACKAGE_FILE_BASE64_CHARS,
    MAX_PACKAGE_FILE_BYTES,
    MAX_PACKAGE_FILE_COUNT,
    MAX_PACKAGE_TOTAL_BYTES,
)

CONTRACT_ID = 'urn:v3:asl:product_entry:1.1.0'
SERVICE = 'ProductEntryService'
API_VERSION = '1.1.0'

_PRJ = r'^prj_[0-9A-HJKMNP-TV-Z]{26}$'
_PCR = r'^pcr_[0-9A-HJKMNP-TV-Z]{26}$'
_BTRS = r'^btrs_sha256_[0-9a-f]{64}$'
_ART = r'^art_sha256_[0-9a-f]{64}$'
_TSK = r'^tsk_[0-9A-HJKMNP-TV-Z]{26}$'
_RUN = r'^run_[0-9A-HJKMNP-TV-Z]{26}$'
_HEX64 = r'^[0-9a-f]{64}$'
_FDOC = r'^fdoc_sha256_[0-9a-f]{64}$'
_FDV = r'^fdv_sha256_[0-9a-f]{64}$'
_FMT = r'^fmt_sha256_[0-9a-f]{64}$'
_FAR = r'^far_sha256_[0-9a-f]{64}$'
_UNV = r'^unv_sha256_[0-9a-f]{64}$'
_RSSV = r'^rssv_sha256_[0-9a-f]{64}$'
_COST = r'^cost_sha256_[0-9a-f]{64}$'
_TIMING = r'^timing_sha256_[0-9a-f]{64}$'
_RULE_PROFILE = r'^atrp_sha256_[0-9a-f]{64}$'
_RPSV = r'^rpsv_sha256_[0-9a-f]{64}$'
_ASSUMPTION = r'^assumption_sha256_[0-9a-f]{64}$'
_CANONICAL_ID = r'^[A-Za-z0-9_-]{1,200}$'
_DATE_YYYYMMDD = r'^[0-9]{8}$'
_SYMBOL = r'^[0-9]{6}$'
# Single-segment relative file names only; the importer rejects anything else.
_PKG_PATH = r'^[a-z0-9][a-z0-9._-]{0,63}$'

# Bounded package transfer limits (well inside the 1 MiB frame budget).
MAX_PACKAGE_FILES = MAX_PACKAGE_FILE_COUNT

_FACTOR_METRIC_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['status', 'value', 'reason'],
    'properties': {
        'status': {'type': 'string', 'enum': ['AVAILABLE', 'INSUFFICIENT_SAMPLE', 'NOT_AVAILABLE']},
        'value': {'type': ['number', 'null']},
        'reason': {'type': ['string', 'null']},
    },
}
_FACTOR_ANALYSIS_SPEC_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'schema_version', 'forward_return_horizon_sessions', 'quantiles',
        'minimum_instruments_per_date', 'minimum_valid_ic_dates',
        'formation_price', 'label_price', 'signal_availability',
    ],
    'properties': {
        'schema_version': {'type': 'string', 'const': 'v3.factor-analysis-spec/1.0.0'},
        'forward_return_horizon_sessions': {'type': 'integer', 'const': 5},
        'quantiles': {'type': 'integer', 'const': 5},
        'minimum_instruments_per_date': {'type': 'integer', 'const': 20},
        'minimum_valid_ic_dates': {'type': 'integer', 'const': 20},
        'formation_price': {'type': 'string', 'const': 'RAW_CLOSE'},
        'label_price': {'type': 'string', 'const': 'RAW_CLOSE'},
        'signal_availability': {'type': 'string', 'const': 'AFTER_SESSION_CLOSE'},
    },
}
_FACTOR_YEARLY_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['year', 'valid_dates', 'ic_mean', 'ic_std', 'icir'],
    'properties': {
        'year': {'type': 'integer'},
        'valid_dates': {'type': 'integer', 'minimum': 0},
        'ic_mean': _FACTOR_METRIC_SCHEMA,
        'ic_std': _FACTOR_METRIC_SCHEMA,
        'icir': _FACTOR_METRIC_SCHEMA,
    },
}
_FACTOR_AGGREGATE_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'valid_dates', 'ic_mean', 'ic_std', 'icir', 'rank_ic_mean',
        'rank_ic_std', 'rank_icir', 'yearly_distribution',
    ],
    'properties': {
        'valid_dates': {'type': 'integer', 'minimum': 0},
        'ic_mean': _FACTOR_METRIC_SCHEMA,
        'ic_std': _FACTOR_METRIC_SCHEMA,
        'icir': _FACTOR_METRIC_SCHEMA,
        'rank_ic_mean': _FACTOR_METRIC_SCHEMA,
        'rank_ic_std': _FACTOR_METRIC_SCHEMA,
        'rank_icir': _FACTOR_METRIC_SCHEMA,
        'yearly_distribution': {'type': 'array', 'items': _FACTOR_YEARLY_SCHEMA},
    },
}
_FACTOR_DAILY_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'session_date', 'label_session_date', 'status', 'reason', 'universe_size',
        'sample_size', 'coverage', 'missing_rate', 'ic', 'rank_ic',
        'quantile_returns', 'long_short_spread', 'turnover', 'diagnostics',
        'excluded_reason_counts',
    ],
    'properties': {
        'session_date': {'type': 'string', 'format': 'date'},
        'label_session_date': {'type': 'string', 'format': 'date'},
        'status': {'type': 'string', 'enum': ['AVAILABLE', 'INSUFFICIENT_SAMPLE', 'NOT_AVAILABLE']},
        'reason': {'type': ['string', 'null']},
        'universe_size': {'type': 'integer', 'minimum': 1},
        'sample_size': {'type': 'integer', 'minimum': 0},
        'coverage': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'missing_rate': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'ic': _FACTOR_METRIC_SCHEMA,
        'rank_ic': _FACTOR_METRIC_SCHEMA,
        'quantile_returns': {'type': ['array', 'null']},
        'long_short_spread': {'type': ['number', 'null']},
        'turnover': _FACTOR_METRIC_SCHEMA,
        'diagnostics': {'type': 'array', 'items': {'type': 'string'}},
        'excluded_reason_counts': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['reason', 'count'],
                'properties': {
                    'reason': {'type': 'string'},
                    'count': {'type': 'integer', 'minimum': 1},
                },
            },
        },
    },
}
_PROJECT_FACTOR_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'schema_version', 'truth', 'admission', 'project_id',
        'project_context_revision_id', 'snapshot_id', 'universe_version_id',
        'source_manifest_artifact_id', 'source_manifest_sha256',
        'formula_document_version_id', 'formula_document_artifact_id',
        'analysis_output_name', 'analysis_artifact_id', 'outputs',
        'visual_preview_total_rows', 'visual_preview_projection',
        'visual_preview', 'analysis',
    ],
    'properties': {
        'schema_version': {'type': 'string', 'const': 'v3.project-factor-summary/1.1.0'},
        'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
        'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
        'project_id': {'type': 'string', 'pattern': _PRJ},
        'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
        'snapshot_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'universe_version_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'source_manifest_artifact_id': {'type': 'string', 'pattern': _ART},
        'source_manifest_sha256': {'type': 'string', 'pattern': _HEX64},
        'formula_document_version_id': {'type': 'string', 'pattern': _FDOC},
        'formula_document_artifact_id': {'type': 'string', 'pattern': _ART},
        'analysis_output_name': {'type': 'string', 'pattern': r'^[A-Za-z_][A-Za-z0-9_]{0,63}$'},
        'analysis_artifact_id': {'type': 'string', 'pattern': _ART},
        'outputs': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'name', 'factor_definition_version_id',
                    'factor_definition_artifact_id', 'materialization_id',
                    'materialization_artifact_id', 'output_type', 'row_count',
                ],
                'properties': {
                    'name': {'type': 'string', 'pattern': r'^[A-Za-z_][A-Za-z0-9_]{0,63}$'},
                    'factor_definition_version_id': {'type': 'string', 'pattern': _FDV},
                    'factor_definition_artifact_id': {'type': 'string', 'pattern': _ART},
                    'materialization_id': {'type': 'string', 'pattern': _FMT},
                    'materialization_artifact_id': {'type': 'string', 'pattern': _ART},
                    'output_type': {'type': 'string', 'enum': ['FLOAT_SERIES', 'BOOLEAN_SERIES']},
                    'row_count': {'type': 'integer', 'minimum': 1, 'maximum': 2000000},
                },
            },
        },
        'visual_preview_total_rows': {
            'type': 'integer', 'minimum': 0, 'maximum': 2000000,
        },
        'visual_preview_projection': {
            'type': 'string', 'const': 'TAIL_ASCENDING_MAX_256',
        },
        'visual_preview': {
            'type': 'array',
            'maxItems': 256,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'session_date', 'instrument_id', 'open', 'high', 'low',
                    'close', 'volume_shares', 'amount_cny', 'series',
                ],
                'properties': {
                    'session_date': {'type': 'string', 'format': 'date'},
                    'instrument_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                    'open': {'type': ['number', 'null']},
                    'high': {'type': ['number', 'null']},
                    'low': {'type': ['number', 'null']},
                    'close': {'type': ['number', 'null']},
                    'volume_shares': {'type': ['number', 'null']},
                    'amount_cny': {'type': ['number', 'null']},
                    'series': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'additionalProperties': False,
                            'required': ['name', 'value'],
                            'properties': {
                                'name': {'type': 'string', 'pattern': r'^[A-Za-z_][A-Za-z0-9_]{0,63}$'},
                                'value': {'type': ['number', 'boolean', 'null']},
                            },
                        },
                    },
                },
            },
        },
        'analysis': {
            'type': 'object',
            'additionalProperties': False,
            'required': [
                'factor_analysis_result_id', 'spec', 'aggregate',
                'daily_result_count', 'daily_results_projection', 'daily_results',
            ],
            'properties': {
                'factor_analysis_result_id': {'type': 'string', 'pattern': _FAR},
                'spec': _FACTOR_ANALYSIS_SPEC_SCHEMA,
                'aggregate': _FACTOR_AGGREGATE_SCHEMA,
                'daily_result_count': {
                    'type': 'integer', 'minimum': 0, 'maximum': 2000000,
                },
                'daily_results_projection': {
                    'type': 'string', 'const': 'TAIL_ASCENDING_MAX_256',
                },
                'daily_results': {
                    'type': 'array', 'maxItems': 256, 'items': _FACTOR_DAILY_SCHEMA,
                },
            },
        },
    },
}
_PROJECT_STRATEGY_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'schema_version', 'truth', 'admission', 'project_id',
        'project_context_revision_id', 'snapshot_id', 'universe_version_id',
        'research_strategy_spec_id', 'strategy_version_id',
        'entry_signal_factor_version_id', 'exit_signal_factor_version_id',
        'profile_refs', 'transition_count', 'decision_chain_count',
    ],
    'properties': {
        'schema_version': {'type': 'string', 'const': 'v3.project-strategy-summary/1.0.0'},
        'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
        'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
        'project_id': {'type': 'string', 'pattern': _PRJ},
        'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
        'snapshot_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'universe_version_id': {'type': 'string', 'pattern': _UNV},
        'research_strategy_spec_id': {'type': 'string', 'pattern': _RSSV},
        'strategy_version_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'entry_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
        'exit_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
        'profile_refs': {
            'type': 'object',
            'additionalProperties': False,
            'required': [
                'cost_policy_version_id', 'execution_policy_version_id',
                'risk_policy_set_version_id', 'assumption_profile_id',
            ],
            'properties': {
                'cost_policy_version_id': {'type': 'string', 'pattern': _COST},
                'execution_policy_version_id': {'type': 'string', 'pattern': _TIMING},
                'risk_policy_set_version_id': {'type': 'string', 'pattern': _RPSV},
                'assumption_profile_id': {'type': 'string', 'pattern': _ASSUMPTION},
            },
        },
        'transition_count': {'type': 'integer', 'minimum': 0, 'maximum': 3000},
        'decision_chain_count': {'type': 'integer', 'minimum': 0, 'maximum': 3000},
    },
}
_PROJECT_STRATEGY_AUTHORING_PROFILE_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'schema_version', 'truth', 'admission', 'position_sizing_options',
        'max_positions_min', 'max_positions_max', 'gross_exposure_min',
        'gross_exposure_max', 'rebalance', 'profile_refs',
        'assumption_profiles',
    ],
    'properties': {
        'schema_version': {
            'type': 'string',
            'const': 'v3.product-strategy-authoring-profile/1.0.0',
        },
        'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
        'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
        'position_sizing_options': {
            'type': 'array',
            'minItems': 2,
            'maxItems': 2,
            'uniqueItems': True,
            'items': {
                'type': 'string',
                'enum': [
                    'SINGLE_ASSET_FULL_WEIGHT',
                    'EQUAL_WEIGHT_ACTIVE_SIGNALS',
                ],
            },
        },
        'max_positions_min': {'type': 'integer', 'const': 1},
        'max_positions_max': {'type': 'integer', 'const': 20},
        'gross_exposure_min': {'type': 'string', 'const': '0'},
        'gross_exposure_max': {'type': 'string', 'const': '1'},
        'rebalance': {'type': 'string', 'const': 'NEXT_OPEN_AFTER_SIGNAL'},
        'profile_refs': {
            'type': 'object',
            'additionalProperties': False,
            'required': [
                'cost_policy_version_id', 'execution_policy_version_id',
                'risk_policy_set_version_id', 'assumption_profile_id',
            ],
            'properties': {
                'cost_policy_version_id': {'type': 'string', 'pattern': _COST},
                'execution_policy_version_id': {'type': 'string', 'pattern': _TIMING},
                'risk_policy_set_version_id': {'type': 'string', 'pattern': _RPSV},
                'assumption_profile_id': {'type': 'string', 'pattern': _ASSUMPTION},
            },
        },
        'assumption_profiles': {
            'type': 'array',
            'minItems': 2,
            'maxItems': 2,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['mode', 'assumption_profile_id'],
                'properties': {
                    'mode': {
                        'type': 'string',
                        'enum': ['RESEARCH_APPROXIMATE', 'STRICT_FAIL_CLOSED'],
                    },
                    'assumption_profile_id': {
                        'type': 'string',
                        'pattern': _ASSUMPTION,
                    },
                },
            },
        },
    },
}
_PROJECT_BACKTEST_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'schema_version', 'maturity', 'truth', 'admission', 'project_id',
        'project_context_revision_id', 'research_backtest_request_id',
        'research_strategy_spec_id', 'snapshot_id', 'universe_version_id',
        'run_id', 'run_spec_id', 'result_id', 'backtest_result_id',
        'result_artifact_id', 'analytics_id', 'analytics_artifact_id',
        'summary_export_artifact_id', 'orders_export_artifact_id',
        'fills_export_artifact_id',
        'result_lineage_id', 'lineage_artifact_id', 'result_state',
        'engine_version', 'order_count', 'fill_count', 'diagnostic_count',
        'first_fill_session_date', 'first_effective_session_date',
        'assumption_mode',
    ],
    'properties': {
        'schema_version': {'type': 'string', 'const': 'v3.project-backtest-summary/1.0.0'},
        'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
        'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
        'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
        'project_id': {'type': 'string', 'pattern': _PRJ},
        'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
        'research_backtest_request_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'research_strategy_spec_id': {'type': 'string', 'pattern': _RSSV},
        'snapshot_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'universe_version_id': {'type': 'string', 'pattern': _UNV},
        'run_id': {'type': 'string', 'pattern': _RUN},
        'run_spec_id': {'type': 'string', 'pattern': _BTRS},
        'result_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'backtest_result_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'result_artifact_id': {'type': 'string', 'pattern': _ART},
        'analytics_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'analytics_artifact_id': {'type': 'string', 'pattern': _ART},
        'summary_export_artifact_id': {'type': 'string', 'pattern': _ART},
        'orders_export_artifact_id': {'type': 'string', 'pattern': _ART},
        'fills_export_artifact_id': {'type': 'string', 'pattern': _ART},
        'result_lineage_id': {'type': 'string', 'pattern': _CANONICAL_ID},
        'lineage_artifact_id': {'type': 'string', 'pattern': _ART},
        'result_state': {'type': 'string', 'const': 'VALID'},
        'engine_version': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'order_count': {'type': 'integer', 'minimum': 0, 'maximum': 2000000},
        'fill_count': {'type': 'integer', 'minimum': 0, 'maximum': 2000000},
        'diagnostic_count': {'type': 'integer', 'minimum': 0, 'maximum': 2000000},
        'first_fill_session_date': {'type': ['string', 'null'], 'format': 'date'},
        'first_effective_session_date': {'type': ['string', 'null'], 'format': 'date'},
        'assumption_mode': {
            'type': 'string',
            'enum': ['RESEARCH_APPROXIMATE', 'STRICT_FAIL_CLOSED'],
        },
    },
}

METHOD_SPECS = {
    'ProductEntryService.v1.listBacktestRunSpecs': {
        'operation_id': 'ProductEntryService.v1.listBacktestRunSpecs',
        'version': '1.0.0',
        'kind': 'QUERY',
        'request_dto': {
            'name': 'ListBacktestRunSpecsRequestV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'project_id', 'project_context_revision_id', 'expected_api_version'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical project identity', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Canonical project context revision identity', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact ASL major.minor expected by caller', 'const': '1.0'},
                    'page': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                            'after_artifact_id': {'type': 'string', 'pattern': _ART},
                        },
                    },
                },
            },
        },
        'response_dto': {
            'name': 'ListBacktestRunSpecsResponseV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'description': 'Explicit capability truth', 'enum': ['FORMAL', 'DEMO', 'UNAVAILABLE']},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version', 'specs', 'has_more',
                            'next_after_artifact_id',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry/1.0'},
                            'specs': {
                                'type': 'array',
                                'maxItems': 100,
                                'items': {
                                    'type': 'object',
                                    'additionalProperties': False,
                                    'required': [
                                        'run_spec_id', 'artifact_id', 'content_sha256',
                                        'project_context_revision_id', 'engine_version',
                                        'created_at', 'execution_adapter_version_id', 'status',
                                        'diagnostic',
                                    ],
                                    'properties': {
                                        'run_spec_id': {'type': ['string', 'null'], 'pattern': _BTRS},
                                        'artifact_id': {'type': 'string', 'pattern': _ART},
                                        'content_sha256': {'type': ['string', 'null'], 'pattern': _HEX64},
                                        'project_context_revision_id': {'type': ['string', 'null'], 'pattern': _PCR},
                                        'engine_version': {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 200},
                                        'created_at': {'type': ['string', 'null'], 'format': 'date-time'},
                                        'execution_adapter_version_id': {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 200},
                                        'status': {'type': 'string', 'enum': ['EXECUTABLE', 'UNAVAILABLE']},
                                        'diagnostic': {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 500},
                                    },
                                },
                            },
                            'has_more': {'type': 'boolean'},
                            'next_after_artifact_id': {
                                'type': ['string', 'null'],
                                'pattern': _ART,
                            },
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.importResearchPackage': {
        'operation_id': 'ProductEntryService.v1.importResearchPackage',
        'version': '1.0.0',
        'kind': 'COMMAND',
        'request_dto': {
            'name': 'ImportResearchPackageRequestV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'project_id', 'project_context_revision_id', 'expected_api_version', 'idempotency_key', 'manifest', 'files'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical project that will own the imported run spec', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Current canonical context revision of the target project', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact ASL major.minor expected by caller', 'const': '1.0'},
                    'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 200, 'description': 'Idempotency key scoped to operation + project'},
                    'manifest': {
                        'type': 'object',
                        'description': 'Closed v3.research-package/1.0.0 manifest (strictly validated by the runtime importer)',
                    },
                    'files': {
                        'type': 'array',
                        'minItems': 1,
                        'maxItems': MAX_PACKAGE_FILES,
                        'items': {
                            'type': 'object',
                            'additionalProperties': False,
                            'required': ['name', 'sha256', 'byte_size', 'payload_base64'],
                            'properties': {
                                'name': {'type': 'string', 'pattern': _PKG_PATH, 'description': 'Relative package payload file name'},
                                'sha256': {'type': 'string', 'pattern': _HEX64, 'description': 'Declared SHA-256 of the actual payload bytes'},
                                'byte_size': {'type': 'integer', 'minimum': 1, 'maximum': MAX_PACKAGE_FILE_BYTES},
                                'payload_base64': {'type': 'string', 'minLength': 4, 'maxLength': MAX_PACKAGE_FILE_BASE64_CHARS, 'description': 'Actual payload bytes (base64)'},
                            },
                        },
                    },
                },
            },
        },
        'response_dto': {
            'name': 'ImportResearchPackageResponseV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'description': 'Explicit capability truth', 'enum': ['FORMAL', 'DEMO', 'UNAVAILABLE']},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version',
                            'run_spec_id', 'run_spec_artifact_id', 'context_artifact_id',
                            'already_imported', 'source_project_id', 'imported_at',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry/1.0'},
                            'run_spec_id': {'type': 'string', 'pattern': _BTRS},
                            'run_spec_artifact_id': {'type': 'string', 'pattern': _ART},
                            'context_artifact_id': {'type': 'string', 'pattern': _ART},
                            'already_imported': {'type': 'boolean', 'description': 'True when the same package was already imported (idempotent replay)'},
                            'source_project_id': {'type': 'string', 'pattern': _PRJ, 'description': 'Canonical source project identity carried by the package provenance'},
                            'imported_at': {'type': 'string', 'format': 'date-time'},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.submitResearch': {
        'operation_id': 'ProductEntryService.v1.submitResearch',
        'version': '1.0.0',
        'kind': 'COMMAND',
        'request_dto': {
            'name': 'SubmitResearchRequestV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version', 'idempotency_key',
                    'research_profile_id', 'strategy_profile_id', 'source',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical project identity', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Canonical project context revision identity', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact ASL major.minor expected by caller', 'const': '1.0'},
                    'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 200, 'description': 'Idempotency key scoped to operation + project'},
                    'research_profile_id': {'type': 'string', 'const': 'RESEARCH_FREE_DATA_V1'},
                    'strategy_profile_id': {'type': 'string', 'const': 'RESEARCH_CLOSE_RANK_TOP1_V1'},
                    'source': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'provider_id', 'connector_version_id', 'logical_dataset',
                            'frequency', 'symbol', 'start_date', 'end_date',
                        ],
                        'properties': {
                            'provider_id': {'type': 'string', 'const': 'pvd_akshare_eastmoney_a_share_eod_v1'},
                            'connector_version_id': {'type': 'string', 'const': 'cov_akshare_eod_research_v1'},
                            'logical_dataset': {'type': 'string', 'const': 'CN_A_SHARE_EOD'},
                            'frequency': {'type': 'string', 'const': 'P1D'},
                            'symbol': {'type': 'string', 'pattern': _SYMBOL},
                            'start_date': {'type': 'string', 'pattern': _DATE_YYYYMMDD},
                            'end_date': {'type': 'string', 'pattern': _DATE_YYYYMMDD},
                        },
                    },
                },
            },
        },
        'response_dto': {
            'name': 'SubmitResearchResponseV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'description': 'Explicit capability truth', 'enum': ['FORMAL', 'DEMO', 'UNAVAILABLE']},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version', 'task_id', 'run_id',
                            'accepted_state', 'maturity', 'research_profile_id',
                            'strategy_profile_id', 'research_classification',
                            'truth_admission',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry-research/1.0'},
                            'task_id': {'type': 'string', 'pattern': _TSK},
                            'run_id': {'type': 'string', 'pattern': _RUN},
                            'accepted_state': {'type': 'string', 'const': 'QUEUED'},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED_CANDIDATE'},
                            'research_profile_id': {'type': 'string', 'const': 'RESEARCH_FREE_DATA_V1'},
                            'strategy_profile_id': {'type': 'string', 'const': 'RESEARCH_CLOSE_RANK_TOP1_V1'},
                            'research_classification': {
                                'type': 'array',
                                'minItems': 2,
                                'maxItems': 2,
                                'uniqueItems': True,
                                'items': {'type': 'string', 'enum': ['RESEARCH_ONLY', 'APPROXIMATE']},
                            },
                            'truth_admission': {
                                'type': 'object',
                                'additionalProperties': False,
                                'required': ['truth', 'admission'],
                                'properties': {
                                    'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                                    'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                                },
                            },
                            'event_cursor': {'type': 'integer', 'minimum': 1},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.importLocalDataset': {
        'operation_id': 'ProductEntryService.v1.importLocalDataset',
        'version': '1.1.0',
        'kind': 'COMMAND',
        'request_dto': {
            'name': 'ImportLocalDatasetRequestV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version', 'idempotency_key', 'source',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical target project identity', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Current canonical target context revision', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact additive Product Entry API expected by caller', 'const': '1.1'},
                    'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 200, 'description': 'Idempotency key scoped to operation + project'},
                    'source': {
                        'type': 'object',
                        'additionalProperties': False,
                        'description': 'Immutable project-scoped local source Artifact ref plus explicit data semantics; never a path or numeric payload',
                        'required': [
                            'artifact_id', 'sha256', 'byte_size', 'media_type',
                            'display_name', 'volume_unit', 'amount_unit',
                            'timezone', 'adjustment',
                        ],
                        'properties': {
                            'artifact_id': {'type': 'string', 'pattern': _ART},
                            'sha256': {'type': 'string', 'pattern': _HEX64},
                            'byte_size': {'type': 'integer', 'minimum': 1, 'maximum': 268435456},
                            'media_type': {'type': 'string', 'enum': ['text/csv', 'application/vnd.apache.parquet']},
                            'display_name': {'type': 'string', 'minLength': 1, 'maxLength': 255, 'pattern': r'^[^/\\]+$'},
                            'volume_unit': {'type': 'string', 'enum': ['SHARES', 'HANDS']},
                            'amount_unit': {'type': 'string', 'const': 'CNY'},
                            'timezone': {'type': 'string', 'const': 'Asia/Shanghai'},
                            'adjustment': {'type': 'string', 'const': 'UNADJUSTED'},
                        },
                    },
                },
            },
        },
        'response_dto': {
            'name': 'ImportLocalDatasetResponseV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'const': 'NOT_FORMAL'},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version', 'task_id', 'run_id',
                            'accepted_state', 'maturity', 'truth', 'admission',
                            'checkpoint_resume', 'retry', 'source_artifact_id',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry-local-data/1.1'},
                            'task_id': {'type': 'string', 'pattern': _TSK},
                            'run_id': {'type': 'string', 'pattern': _RUN},
                            'accepted_state': {'type': 'string', 'const': 'QUEUED'},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
                            'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                            'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                            'checkpoint_resume': {'type': 'string', 'const': 'UNAVAILABLE'},
                            'retry': {'type': 'string', 'const': 'NEW_ATTEMPT_SAME_RUN_FROM_START'},
                            'source_artifact_id': {'type': 'string', 'pattern': _ART},
                            'event_cursor': {'type': 'integer', 'minimum': 1},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.submitFactorStudy': {
        'operation_id': 'ProductEntryService.v1.submitFactorStudy',
        'version': '1.1.0',
        'kind': 'COMMAND',
        'request_dto': {
            'name': 'SubmitFactorStudyRequestV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version', 'idempotency_key', 'formula_source',
                    'analysis_output_name',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical target project identity', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Current canonical target context revision', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact additive Product Entry API expected by caller', 'const': '1.1'},
                    'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 200, 'description': 'Idempotency key scoped to operation + project'},
                    'formula_source': {'type': 'string', 'minLength': 1, 'maxLength': 65536, 'description': 'User-authored bounded TDX source; never factor values or owner IDs'},
                    'analysis_output_name': {'type': 'string', 'pattern': r'^[A-Za-z_][A-Za-z0-9_]{0,63}$'},
                },
            },
        },
        'response_dto': {
            'name': 'SubmitFactorStudyResponseV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'const': 'NOT_FORMAL'},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version', 'task_id', 'run_id',
                            'accepted_state', 'maturity', 'truth', 'admission',
                            'checkpoint_resume', 'retry',
                            'formula_document_version_id', 'analysis_output_name',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry-factor-study/1.1'},
                            'task_id': {'type': 'string', 'pattern': _TSK},
                            'run_id': {'type': 'string', 'pattern': _RUN},
                            'accepted_state': {'type': 'string', 'const': 'QUEUED'},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
                            'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                            'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                            'checkpoint_resume': {'type': 'string', 'const': 'UNAVAILABLE'},
                            'retry': {'type': 'string', 'const': 'NEW_ATTEMPT_SAME_RUN_FROM_START'},
                            'formula_document_version_id': {'type': 'string', 'pattern': _FDOC},
                            'analysis_output_name': {'type': 'string', 'pattern': r'^[A-Za-z_][A-Za-z0-9_]{0,63}$'},
                            'event_cursor': {'type': 'integer', 'minimum': 1},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.previewResearchStrategy': {
        'operation_id': 'ProductEntryService.v1.previewResearchStrategy',
        'version': '1.1.0',
        'kind': 'QUERY',
        'request_dto': {
            'name': 'PreviewResearchStrategyRequestV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version', 'universe_version_id',
                    'entry_signal_factor_version_id', 'exit_signal_factor_version_id',
                    'position_sizing', 'max_positions', 'gross_exposure', 'rebalance',
                    'cost_policy_version_id', 'execution_policy_version_id',
                    'risk_policy_set_version_id', 'initial_cash', 'assumption_profile_id',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'const': '1.1'},
                    'universe_version_id': {'type': 'string', 'pattern': _UNV},
                    'entry_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
                    'exit_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
                    'position_sizing': {'type': 'string', 'enum': ['SINGLE_ASSET_FULL_WEIGHT', 'EQUAL_WEIGHT_ACTIVE_SIGNALS']},
                    'max_positions': {'type': 'integer', 'minimum': 1, 'maximum': 20},
                    'gross_exposure': {'type': 'string', 'pattern': r'^(?:0(?:\.[0-9]+)?|1(?:\.0+)?)$'},
                    'rebalance': {'type': 'string', 'const': 'NEXT_OPEN_AFTER_SIGNAL'},
                    'cost_policy_version_id': {'type': 'string', 'pattern': _COST},
                    'execution_policy_version_id': {'type': 'string', 'pattern': _TIMING},
                    'risk_policy_set_version_id': {'type': 'string', 'pattern': _RPSV},
                    'initial_cash': {'type': 'string', 'pattern': r'^(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)$'},
                    'assumption_profile_id': {'type': 'string', 'pattern': _ASSUMPTION},
                },
            },
        },
        'response_dto': {
            'name': 'PreviewResearchStrategyResponseV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'const': 'NOT_FORMAL'},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'schema_version', 'maturity', 'truth', 'admission',
                            'project_id', 'project_context_revision_id', 'snapshot_id',
                            'universe_version_id', 'research_strategy_spec_id',
                            'strategy_definition_version_id',
                            'entry_signal_factor_version_id', 'exit_signal_factor_version_id',
                            'profile_refs', 'assumption_mode', 'transition_count',
                            'planned_decision_chain_count', 'side_effects',
                        ],
                        'properties': {
                            'schema_version': {'type': 'string', 'const': 'v3.product-strategy-preview/1.0.0'},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
                            'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                            'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                            'project_id': {'type': 'string', 'pattern': _PRJ},
                            'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                            'snapshot_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                            'universe_version_id': {'type': 'string', 'pattern': _UNV},
                            'research_strategy_spec_id': {'type': 'string', 'pattern': _RSSV},
                            'strategy_definition_version_id': {'type': 'string', 'pattern': '^sdv_sha256_[0-9a-f]{64}$'},
                            'entry_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
                            'exit_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
                            'profile_refs': {
                                'type': 'object', 'additionalProperties': False,
                                'required': ['cost_policy_version_id', 'execution_policy_version_id', 'risk_policy_set_version_id', 'assumption_profile_id'],
                                'properties': {
                                    'cost_policy_version_id': {'type': 'string', 'pattern': _COST},
                                    'execution_policy_version_id': {'type': 'string', 'pattern': _TIMING},
                                    'risk_policy_set_version_id': {'type': 'string', 'pattern': _RPSV},
                                    'assumption_profile_id': {'type': 'string', 'pattern': _ASSUMPTION},
                                },
                            },
                            'assumption_mode': {'type': 'string', 'enum': ['RESEARCH_APPROXIMATE', 'STRICT_FAIL_CLOSED']},
                            'transition_count': {'type': 'integer', 'minimum': 0, 'maximum': 2000000},
                            'planned_decision_chain_count': {'type': 'integer', 'minimum': 0, 'maximum': 2000000},
                            'side_effects': {'type': 'string', 'const': 'NONE'},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.publishResearchStrategy': {
        'operation_id': 'ProductEntryService.v1.publishResearchStrategy',
        'version': '1.1.0',
        'kind': 'COMMAND',
        'request_dto': {
            'name': 'PublishResearchStrategyRequestV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version', 'idempotency_key',
                    'universe_version_id', 'entry_signal_factor_version_id',
                    'exit_signal_factor_version_id', 'position_sizing',
                    'max_positions', 'gross_exposure', 'rebalance',
                    'cost_policy_version_id', 'execution_policy_version_id',
                    'risk_policy_set_version_id', 'initial_cash',
                    'assumption_profile_id',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical target project identity', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Current canonical target context revision', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact additive Product Entry API expected by caller', 'const': '1.1'},
                    'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 200, 'description': 'Idempotency key scoped to operation + project'},
                    'universe_version_id': {'type': 'string', 'pattern': _UNV},
                    'entry_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
                    'exit_signal_factor_version_id': {'type': 'string', 'pattern': _FDV},
                    'position_sizing': {'type': 'string', 'enum': ['SINGLE_ASSET_FULL_WEIGHT', 'EQUAL_WEIGHT_ACTIVE_SIGNALS']},
                    'max_positions': {'type': 'integer', 'minimum': 1, 'maximum': 20},
                    'gross_exposure': {'type': 'string', 'pattern': r'^(?:0(?:\.[0-9]+)?|1(?:\.0+)?)$'},
                    'rebalance': {'type': 'string', 'const': 'NEXT_OPEN_AFTER_SIGNAL'},
                    'cost_policy_version_id': {'type': 'string', 'pattern': _COST},
                    'execution_policy_version_id': {'type': 'string', 'pattern': _TIMING},
                    'risk_policy_set_version_id': {'type': 'string', 'pattern': _RPSV},
                    'initial_cash': {'type': 'string', 'pattern': r'^(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)$'},
                    'assumption_profile_id': {'type': 'string', 'pattern': _ASSUMPTION},
                },
            },
        },
        'response_dto': {
            'name': 'PublishResearchStrategyResponseV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'const': 'NOT_FORMAL'},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version', 'task_id', 'run_id',
                            'accepted_state', 'maturity', 'truth', 'admission',
                            'checkpoint_resume', 'retry',
                            'research_strategy_spec_id',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry-research-strategy/1.1'},
                            'task_id': {'type': 'string', 'pattern': _TSK},
                            'run_id': {'type': 'string', 'pattern': _RUN},
                            'accepted_state': {'type': 'string', 'const': 'QUEUED'},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
                            'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                            'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                            'checkpoint_resume': {'type': 'string', 'const': 'UNAVAILABLE'},
                            'retry': {'type': 'string', 'const': 'NEW_ATTEMPT_SAME_RUN_FROM_START'},
                            'research_strategy_spec_id': {'type': 'string', 'pattern': _RSSV},
                            'event_cursor': {'type': 'integer', 'minimum': 1},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.previewResearchBacktest': {
        'operation_id': 'ProductEntryService.v1.previewResearchBacktest',
        'version': '1.1.0',
        'kind': 'QUERY',
        'request_dto': {
            'name': 'PreviewResearchBacktestRequestV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version', 'research_strategy_spec_id',
                    'session_start', 'session_end', 'slippage_bps',
                    'daily_volume_participation_rate',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'const': '1.1'},
                    'research_strategy_spec_id': {'type': 'string', 'pattern': _RSSV},
                    'session_start': {'type': 'string', 'format': 'date'},
                    'session_end': {'type': 'string', 'format': 'date'},
                    'slippage_bps': {'type': 'string', 'pattern': r'^(?:0(?:\.[0-9]+)?|[1-9][0-9]*(?:\.[0-9]+)?)$'},
                    'daily_volume_participation_rate': {'type': 'string', 'pattern': r'^(?:0(?:\.[0-9]*[1-9][0-9]*)?|1(?:\.0+)?)$'},
                },
            },
        },
        'response_dto': {
            'name': 'PreviewResearchBacktestResponseV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'const': 'NOT_FORMAL'},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'schema_version', 'maturity', 'truth', 'admission',
                            'status', 'project_id', 'project_context_revision_id',
                            'research_strategy_spec_id', 'research_backtest_request_id',
                            'snapshot_id', 'universe_version_id', 'session_start',
                            'session_end', 'slippage_bps',
                            'daily_volume_participation_rate', 'commission_rate',
                            'minimum_commission_cny', 'stamp_duty_sell_rate',
                            'assumption_mode', 'policy_refs', 'resource_estimate',
                            'side_effects',
                        ],
                        'properties': {
                            'schema_version': {'type': 'string', 'const': 'v3.product-backtest-preflight/1.0.0'},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
                            'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                            'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                            'status': {'type': 'string', 'const': 'PASS'},
                            'project_id': {'type': 'string', 'pattern': _PRJ},
                            'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                            'research_strategy_spec_id': {'type': 'string', 'pattern': _RSSV},
                            'research_backtest_request_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                            'snapshot_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                            'universe_version_id': {'type': 'string', 'pattern': _UNV},
                            'session_start': {'type': 'string', 'format': 'date'},
                            'session_end': {'type': 'string', 'format': 'date'},
                            'slippage_bps': {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$'},
                            'daily_volume_participation_rate': {'type': 'string', 'pattern': r'^(?:0(?:\.[0-9]*[1-9][0-9]*)?|1(?:\.0+)?)$'},
                            'commission_rate': {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$'},
                            'minimum_commission_cny': {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$'},
                            'stamp_duty_sell_rate': {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$'},
                            'assumption_mode': {'type': 'string', 'enum': ['RESEARCH_APPROXIMATE', 'STRICT_FAIL_CLOSED']},
                            'policy_refs': {
                                'type': 'object', 'additionalProperties': False,
                                'required': ['rule_profile_id', 'cost_policy_id', 'execution_timing_profile_id', 'risk_policy_set_version_id'],
                                'properties': {
                                    'rule_profile_id': {'type': 'string', 'pattern': _RULE_PROFILE},
                                    'cost_policy_id': {'type': 'string', 'pattern': _COST},
                                    'execution_timing_profile_id': {'type': 'string', 'pattern': _TIMING},
                                    'risk_policy_set_version_id': {'type': 'string', 'pattern': _RPSV},
                                },
                            },
                            'resource_estimate': {
                                'type': 'object', 'additionalProperties': False,
                                'required': ['resource_class', 'cpu_slots', 'memory_limit_bytes', 'scratch_limit_bytes', 'checkpoint_resume'],
                                'properties': {
                                    'resource_class': {'type': 'string', 'const': 'PRODUCT_BACKTEST_CPU'},
                                    'cpu_slots': {'type': 'integer', 'const': 1},
                                    'memory_limit_bytes': {'type': 'integer', 'const': 1073741824},
                                    'scratch_limit_bytes': {'type': 'integer', 'const': 1073741824},
                                    'checkpoint_resume': {'type': 'string', 'const': 'UNAVAILABLE'},
                                },
                            },
                            'side_effects': {'type': 'string', 'const': 'NONE'},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.submitResearchBacktest': {
        'operation_id': 'ProductEntryService.v1.submitResearchBacktest',
        'version': '1.1.0',
        'kind': 'COMMAND',
        'request_dto': {
            'name': 'SubmitResearchBacktestRequestV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version', 'idempotency_key',
                    'research_strategy_spec_id', 'session_start', 'session_end',
                    'slippage_bps', 'daily_volume_participation_rate',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'const': '1.1'},
                    'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                    'research_strategy_spec_id': {'type': 'string', 'pattern': _RSSV},
                    'session_start': {'type': 'string', 'format': 'date'},
                    'session_end': {'type': 'string', 'format': 'date'},
                    'slippage_bps': {'type': 'string', 'pattern': r'^(?:0(?:\.[0-9]+)?|[1-9][0-9]*(?:\.[0-9]+)?)$'},
                    'daily_volume_participation_rate': {'type': 'string', 'pattern': r'^(?:0(?:\.[0-9]*[1-9][0-9]*)?|1(?:\.0+)?)$'},
                },
            },
        },
        'response_dto': {
            'name': 'SubmitResearchBacktestResponseV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'const': 'NOT_FORMAL'},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version', 'task_id', 'run_id',
                            'accepted_state', 'maturity', 'truth', 'admission',
                            'checkpoint_resume', 'retry',
                            'research_backtest_request_id',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry-research-backtest/1.1'},
                            'task_id': {'type': 'string', 'pattern': _TSK},
                            'run_id': {'type': 'string', 'pattern': _RUN},
                            'accepted_state': {'type': 'string', 'const': 'QUEUED'},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
                            'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                            'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                            'checkpoint_resume': {'type': 'string', 'const': 'UNAVAILABLE'},
                            'retry': {'type': 'string', 'const': 'NEW_ATTEMPT_SAME_RUN_FROM_START'},
                            'research_backtest_request_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                            'event_cursor': {'type': 'integer', 'minimum': 1},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.getProjectHome': {
        'operation_id': 'ProductEntryService.v1.getProjectHome',
        'version': '1.1.0',
        'kind': 'QUERY',
        'request_dto': {
            'name': 'GetProjectHomeRequestV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id', 'project_id', 'project_context_revision_id',
                    'expected_api_version',
                ],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical target project identity', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Current canonical target context revision', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact additive Product Entry API expected by caller', 'const': '1.1'},
                },
            },
        },
        'response_dto': {
            'name': 'GetProjectHomeResponseV1_1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'const': 'NOT_FORMAL'},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version', 'project_id',
                            'project_context_revision_id', 'maturity', 'truth',
                            'admission', 'local_import_state', 'data_state',
                            'data_unavailable_reason', 'factor_state',
                            'factor_unavailable_reason', 'strategy_state',
                            'strategy_authoring_profile',
                            'backtest_policy_coverage',
                            'strategy_unavailable_reason', 'backtest_state',
                            'backtest_unavailable_reason',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.project-home/1.1'},
                            'project_id': {'type': 'string', 'pattern': _PRJ},
                            'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                            'maturity': {'type': 'string', 'const': 'PRODUCT_CONNECTED'},
                            'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                            'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                            'local_import_state': {'type': 'string', 'const': 'AVAILABLE'},
                            'data_state': {'type': 'string', 'enum': ['EMPTY', 'AVAILABLE', 'UNAVAILABLE']},
                            'data_unavailable_reason': {'type': 'string', 'enum': ['NONE', 'NO_SNAPSHOT', 'DATA_READ_MODEL_NOT_AVAILABLE']},
                            'factor_state': {'type': 'string', 'enum': ['EMPTY', 'AVAILABLE', 'UNAVAILABLE']},
                            'factor_unavailable_reason': {'type': 'string', 'enum': ['NONE', 'NO_SNAPSHOT', 'NO_FACTOR_STUDY', 'FACTOR_READ_MODEL_NOT_AVAILABLE']},
                            'factor': _PROJECT_FACTOR_SCHEMA,
                            'strategy_authoring_profile': _PROJECT_STRATEGY_AUTHORING_PROFILE_SCHEMA,
                            'backtest_policy_coverage': {
                                'type': 'object',
                                'additionalProperties': False,
                                'required': [
                                    'schema_version', 'truth', 'admission',
                                    'coverage_start', 'coverage_end',
                                    'rule_profile_id', 'cost_policy_id',
                                    'execution_timing_profile_id',
                                    'commission_rate', 'minimum_commission_cny',
                                    'stamp_duty_sell_rate', 'resource_estimate',
                                ],
                                'properties': {
                                    'schema_version': {'type': 'string', 'const': 'v3.product-backtest-policy-coverage/1.0.0'},
                                    'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                                    'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                                    'coverage_start': {'type': 'string', 'format': 'date'},
                                    'coverage_end': {'anyOf': [{'type': 'string', 'format': 'date'}, {'type': 'null'}]},
                                    'rule_profile_id': {'type': 'string', 'pattern': _RULE_PROFILE},
                                    'cost_policy_id': {'type': 'string', 'pattern': _COST},
                                    'execution_timing_profile_id': {'type': 'string', 'pattern': _TIMING},
                                    'commission_rate': {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$'},
                                    'minimum_commission_cny': {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$'},
                                    'stamp_duty_sell_rate': {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$'},
                                    'resource_estimate': {
                                        'type': 'object', 'additionalProperties': False,
                                        'required': ['resource_class', 'cpu_slots', 'memory_limit_bytes', 'scratch_limit_bytes', 'checkpoint_resume'],
                                        'properties': {
                                            'resource_class': {'type': 'string', 'const': 'PRODUCT_BACKTEST_CPU'},
                                            'cpu_slots': {'type': 'integer', 'const': 1},
                                            'memory_limit_bytes': {'type': 'integer', 'const': 1073741824},
                                            'scratch_limit_bytes': {'type': 'integer', 'const': 1073741824},
                                            'checkpoint_resume': {'type': 'string', 'const': 'UNAVAILABLE'},
                                        },
                                    },
                                },
                            },
                            'strategy_state': {'type': 'string', 'enum': ['EMPTY', 'AVAILABLE', 'UNAVAILABLE']},
                            'strategy_unavailable_reason': {'type': 'string', 'enum': ['NONE', 'NO_FACTOR_STUDY', 'NO_RESEARCH_STRATEGY', 'STRATEGY_READ_MODEL_NOT_AVAILABLE']},
                            'strategy': _PROJECT_STRATEGY_SCHEMA,
                            'backtest_state': {'type': 'string', 'enum': ['EMPTY', 'AVAILABLE', 'UNAVAILABLE']},
                            'backtest_unavailable_reason': {'type': 'string', 'enum': ['NONE', 'NO_RESEARCH_STRATEGY', 'NO_VALID_BACKTEST', 'BACKTEST_READ_MODEL_NOT_AVAILABLE']},
                            'backtest': _PROJECT_BACKTEST_SCHEMA,
                            'data': {
                                'type': 'object',
                                'additionalProperties': False,
                                'required': [
                                    'schema_version', 'project_id',
                                    'project_context_revision_id', 'display_name',
                                    'truth', 'admission', 'source_type', 'pit_state',
                                    'media_type', 'row_count', 'instrument_count',
                                    'date_coverage_start', 'date_coverage_end',
                                    'partition_count', 'universe_role',
                                    'quality_status', 'validation_profile_id',
                                    'capability_reasons',
                                    'volume_unit', 'amount_unit', 'adjustment',
                                    'raw_capture_id', 'raw_content_hash', 'snapshot_id',
                                    'normalized_payload_hash', 'universe_version_id',
                                    'imported_at', 'raw_artifact_id',
                                ],
                                'properties': {
                                    'schema_version': {'type': 'string', 'const': 'v3.product-data-read-model/1.0.0'},
                                    'project_id': {'type': 'string', 'pattern': _PRJ},
                                    'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                                    'display_name': {'type': 'string', 'minLength': 1, 'maxLength': 255},
                                    'truth': {'type': 'string', 'const': 'NOT_FORMAL'},
                                    'admission': {'type': 'string', 'const': 'PRE_ALPHA'},
                                    'source_type': {'type': 'string', 'const': 'LOCAL_USER_SUPPLIED'},
                                    'pit_state': {'type': 'string', 'const': 'PIT_UNPROVABLE'},
                                    'media_type': {'type': 'string', 'enum': ['text/csv', 'application/vnd.apache.parquet']},
                                    'row_count': {'type': 'integer', 'minimum': 1, 'maximum': 2000000},
                                    'instrument_count': {'type': 'integer', 'minimum': 1, 'maximum': 2000},
                                    'date_coverage_start': {'type': 'string', 'format': 'date'},
                                    'date_coverage_end': {'type': 'string', 'format': 'date'},
                                    'partition_count': {'type': 'integer', 'minimum': 1, 'maximum': 2000000},
                                    'universe_role': {'type': 'string', 'const': 'USER_DEFINED_STATIC'},
                                    'quality_status': {'type': 'string', 'const': 'PASS'},
                                    'validation_profile_id': {'type': 'string', 'const': 'svp_local_user_supplied_v1'},
                                    'capability_reasons': {
                                        'type': 'object',
                                        'additionalProperties': False,
                                        'required': ['pit', 'revision', 'calendar', 'status'],
                                        'properties': {
                                            'pit': {'type': 'string', 'const': 'PIT_UNPROVABLE'},
                                            'revision': {'type': 'string', 'const': 'PROVIDER_REVISION_UNKNOWN'},
                                            'calendar': {'type': 'string', 'const': 'OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR'},
                                            'status': {'type': 'string', 'const': 'SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED'},
                                        },
                                    },
                                    'volume_unit': {'type': 'string', 'const': 'SHARES'},
                                    'amount_unit': {'type': 'string', 'const': 'CNY'},
                                    'adjustment': {'type': 'string', 'const': 'UNADJUSTED'},
                                    'raw_capture_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                                    'raw_content_hash': {'type': 'string', 'pattern': _HEX64},
                                    'snapshot_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                                    'normalized_payload_hash': {'type': 'string', 'pattern': _HEX64},
                                    'universe_version_id': {'type': 'string', 'pattern': _CANONICAL_ID},
                                    'imported_at': {'type': 'string', 'format': 'date-time'},
                                    'raw_artifact_id': {'type': 'string', 'pattern': _ART},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


class ListBacktestRunSpecsRequestV1(ClosedDto):
    DTO_NAME = 'ListBacktestRunSpecsRequestV1'
    OPERATION_ID = 'ProductEntryService.v1.listBacktestRunSpecs'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.listBacktestRunSpecs']['request_dto']['schema']


class ListBacktestRunSpecsResponseV1(ClosedDto):
    DTO_NAME = 'ListBacktestRunSpecsResponseV1'
    OPERATION_ID = 'ProductEntryService.v1.listBacktestRunSpecs'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.listBacktestRunSpecs']['response_dto']['schema']

    def __init__(self, **values):
        super().__init__(**values)
        specs = values['read_model']['specs']
        metadata_schemas = {
            'run_spec_id': {'type': 'string', 'pattern': _BTRS},
            'content_sha256': {'type': 'string', 'pattern': _HEX64},
            'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
            'engine_version': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'created_at': {'type': 'string', 'format': 'date-time'},
            'execution_adapter_version_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        }
        for index, item in enumerate(specs):
            path = f'$.read_model.specs[{index}]'
            status = item['status']
            diagnostic = item['diagnostic']
            if status == 'EXECUTABLE':
                if diagnostic is not None:
                    raise ContractValidationError(
                        f'{path}.diagnostic', 'EXECUTABLE diagnostic must be null'
                    )
                for name, schema in metadata_schemas.items():
                    if item[name] is None:
                        raise ContractValidationError(
                            f'{path}.{name}', f'EXECUTABLE {name} must be canonical metadata'
                        )
                    validate_schema(item[name], schema, f'{path}.{name}')
                continue
            if not isinstance(diagnostic, str) or not diagnostic.strip():
                raise ContractValidationError(
                    f'{path}.diagnostic', 'UNAVAILABLE diagnostic must be non-empty'
                )
            for name, schema in metadata_schemas.items():
                if item[name] is not None:
                    validate_schema(item[name], schema, f'{path}.{name}')


class ImportResearchPackageRequestV1(ClosedDto):
    DTO_NAME = 'ImportResearchPackageRequestV1'
    OPERATION_ID = 'ProductEntryService.v1.importResearchPackage'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.importResearchPackage']['request_dto']['schema']


class ImportResearchPackageResponseV1(ClosedDto):
    DTO_NAME = 'ImportResearchPackageResponseV1'
    OPERATION_ID = 'ProductEntryService.v1.importResearchPackage'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.importResearchPackage']['response_dto']['schema']


class SubmitResearchRequestV1(ClosedDto):
    DTO_NAME = 'SubmitResearchRequestV1'
    OPERATION_ID = 'ProductEntryService.v1.submitResearch'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.submitResearch']['request_dto']['schema']


class SubmitResearchResponseV1(ClosedDto):
    DTO_NAME = 'SubmitResearchResponseV1'
    OPERATION_ID = 'ProductEntryService.v1.submitResearch'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.submitResearch']['response_dto']['schema']


class ImportLocalDatasetRequestV1_1(ClosedDto):
    DTO_NAME = 'ImportLocalDatasetRequestV1_1'
    OPERATION_ID = 'ProductEntryService.v1.importLocalDataset'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.importLocalDataset']['request_dto']['schema']


class ImportLocalDatasetResponseV1_1(ClosedDto):
    DTO_NAME = 'ImportLocalDatasetResponseV1_1'
    OPERATION_ID = 'ProductEntryService.v1.importLocalDataset'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.importLocalDataset']['response_dto']['schema']


class GetProjectHomeRequestV1_1(ClosedDto):
    DTO_NAME = 'GetProjectHomeRequestV1_1'
    OPERATION_ID = 'ProductEntryService.v1.getProjectHome'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.getProjectHome']['request_dto']['schema']


class GetProjectHomeResponseV1_1(ClosedDto):
    DTO_NAME = 'GetProjectHomeResponseV1_1'
    OPERATION_ID = 'ProductEntryService.v1.getProjectHome'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.getProjectHome']['response_dto']['schema']


class SubmitFactorStudyRequestV1_1(ClosedDto):
    DTO_NAME = 'SubmitFactorStudyRequestV1_1'
    OPERATION_ID = 'ProductEntryService.v1.submitFactorStudy'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.submitFactorStudy']['request_dto']['schema']


class SubmitFactorStudyResponseV1_1(ClosedDto):
    DTO_NAME = 'SubmitFactorStudyResponseV1_1'
    OPERATION_ID = 'ProductEntryService.v1.submitFactorStudy'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.submitFactorStudy']['response_dto']['schema']


class PublishResearchStrategyRequestV1_1(ClosedDto):
    DTO_NAME = 'PublishResearchStrategyRequestV1_1'
    OPERATION_ID = 'ProductEntryService.v1.publishResearchStrategy'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.publishResearchStrategy']['request_dto']['schema']


class PublishResearchStrategyResponseV1_1(ClosedDto):
    DTO_NAME = 'PublishResearchStrategyResponseV1_1'
    OPERATION_ID = 'ProductEntryService.v1.publishResearchStrategy'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.publishResearchStrategy']['response_dto']['schema']


class PreviewResearchStrategyRequestV1_1(ClosedDto):
    DTO_NAME = 'PreviewResearchStrategyRequestV1_1'
    OPERATION_ID = 'ProductEntryService.v1.previewResearchStrategy'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.previewResearchStrategy']['request_dto']['schema']


class PreviewResearchStrategyResponseV1_1(ClosedDto):
    DTO_NAME = 'PreviewResearchStrategyResponseV1_1'
    OPERATION_ID = 'ProductEntryService.v1.previewResearchStrategy'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.previewResearchStrategy']['response_dto']['schema']


class PreviewResearchBacktestRequestV1_1(ClosedDto):
    DTO_NAME = 'PreviewResearchBacktestRequestV1_1'
    OPERATION_ID = 'ProductEntryService.v1.previewResearchBacktest'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.previewResearchBacktest']['request_dto']['schema']


class PreviewResearchBacktestResponseV1_1(ClosedDto):
    DTO_NAME = 'PreviewResearchBacktestResponseV1_1'
    OPERATION_ID = 'ProductEntryService.v1.previewResearchBacktest'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.previewResearchBacktest']['response_dto']['schema']


class SubmitResearchBacktestRequestV1_1(ClosedDto):
    DTO_NAME = 'SubmitResearchBacktestRequestV1_1'
    OPERATION_ID = 'ProductEntryService.v1.submitResearchBacktest'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.submitResearchBacktest']['request_dto']['schema']


class SubmitResearchBacktestResponseV1_1(ClosedDto):
    DTO_NAME = 'SubmitResearchBacktestResponseV1_1'
    OPERATION_ID = 'ProductEntryService.v1.submitResearchBacktest'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.submitResearchBacktest']['response_dto']['schema']


OPERATION_IDS = (
    'ProductEntryService.v1.listBacktestRunSpecs',
    'ProductEntryService.v1.importResearchPackage',
    'ProductEntryService.v1.submitResearch',
    'ProductEntryService.v1.importLocalDataset',
    'ProductEntryService.v1.submitFactorStudy',
    'ProductEntryService.v1.previewResearchStrategy',
    'ProductEntryService.v1.publishResearchStrategy',
    'ProductEntryService.v1.previewResearchBacktest',
    'ProductEntryService.v1.submitResearchBacktest',
    'ProductEntryService.v1.getProjectHome',
)
OPERATIONS = (
    OperationContract(
        operation_id='ProductEntryService.v1.listBacktestRunSpecs',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ListBacktestRunSpecsRequestV1,
        response_type=ListBacktestRunSpecsResponseV1,
        metadata=METHOD_SPECS['ProductEntryService.v1.listBacktestRunSpecs'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.importResearchPackage',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=ImportResearchPackageRequestV1,
        response_type=ImportResearchPackageResponseV1,
        metadata=METHOD_SPECS['ProductEntryService.v1.importResearchPackage'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.submitResearch',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=SubmitResearchRequestV1,
        response_type=SubmitResearchResponseV1,
        metadata=METHOD_SPECS['ProductEntryService.v1.submitResearch'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.importLocalDataset',
        service=SERVICE,
        version='1.1.0',
        kind=OperationKind.COMMAND,
        request_type=ImportLocalDatasetRequestV1_1,
        response_type=ImportLocalDatasetResponseV1_1,
        metadata=METHOD_SPECS['ProductEntryService.v1.importLocalDataset'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.submitFactorStudy',
        service=SERVICE,
        version='1.1.0',
        kind=OperationKind.COMMAND,
        request_type=SubmitFactorStudyRequestV1_1,
        response_type=SubmitFactorStudyResponseV1_1,
        metadata=METHOD_SPECS['ProductEntryService.v1.submitFactorStudy'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.previewResearchStrategy',
        service=SERVICE,
        version='1.1.0',
        kind=OperationKind.QUERY,
        request_type=PreviewResearchStrategyRequestV1_1,
        response_type=PreviewResearchStrategyResponseV1_1,
        metadata=METHOD_SPECS['ProductEntryService.v1.previewResearchStrategy'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.publishResearchStrategy',
        service=SERVICE,
        version='1.1.0',
        kind=OperationKind.COMMAND,
        request_type=PublishResearchStrategyRequestV1_1,
        response_type=PublishResearchStrategyResponseV1_1,
        metadata=METHOD_SPECS['ProductEntryService.v1.publishResearchStrategy'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.previewResearchBacktest',
        service=SERVICE,
        version='1.1.0',
        kind=OperationKind.QUERY,
        request_type=PreviewResearchBacktestRequestV1_1,
        response_type=PreviewResearchBacktestResponseV1_1,
        metadata=METHOD_SPECS['ProductEntryService.v1.previewResearchBacktest'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.submitResearchBacktest',
        service=SERVICE,
        version='1.1.0',
        kind=OperationKind.COMMAND,
        request_type=SubmitResearchBacktestRequestV1_1,
        response_type=SubmitResearchBacktestResponseV1_1,
        metadata=METHOD_SPECS['ProductEntryService.v1.submitResearchBacktest'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.getProjectHome',
        service=SERVICE,
        version='1.1.0',
        kind=OperationKind.QUERY,
        request_type=GetProjectHomeRequestV1_1,
        response_type=GetProjectHomeResponseV1_1,
        metadata=METHOD_SPECS['ProductEntryService.v1.getProjectHome'],
    ),
)
CONTRACT = ServiceContract(
    contract_id=CONTRACT_ID,
    service=SERVICE,
    api_version=API_VERSION,
    operations=OPERATIONS,
)

__all__ = (
    'CONTRACT_ID',
    'SERVICE',
    'API_VERSION',
    'OPERATION_IDS',
    'OPERATIONS',
    'CONTRACT',
    'MAX_PACKAGE_FILES',
    'MAX_PACKAGE_FILE_BYTES',
    'MAX_PACKAGE_TOTAL_BYTES',
    'ListBacktestRunSpecsRequestV1',
    'ListBacktestRunSpecsResponseV1',
    'ImportResearchPackageRequestV1',
    'ImportResearchPackageResponseV1',
    'SubmitResearchRequestV1',
    'SubmitResearchResponseV1',
    'ImportLocalDatasetRequestV1_1',
    'ImportLocalDatasetResponseV1_1',
    'SubmitFactorStudyRequestV1_1',
    'SubmitFactorStudyResponseV1_1',
    'PublishResearchStrategyRequestV1_1',
    'PublishResearchStrategyResponseV1_1',
    'PreviewResearchBacktestRequestV1_1',
    'PreviewResearchBacktestResponseV1_1',
    'SubmitResearchBacktestRequestV1_1',
    'SubmitResearchBacktestResponseV1_1',
    'GetProjectHomeRequestV1_1',
    'GetProjectHomeResponseV1_1',
)

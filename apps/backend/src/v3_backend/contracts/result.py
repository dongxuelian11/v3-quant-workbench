from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:result:1.0.0'
SERVICE = 'ResultService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'ResultService.v1.reconcileLedger': {'operation_id': 'ResultService.v1.reconcileLedger',
                                      'version': '1.0.0',
                                      'kind': 'ASYNC_COMMAND',
                                      'request_dto': {'name': 'ReconcileLedgerRequestV1',
                                                      'schema': {'type': 'object',
                                                                 'additionalProperties': False,
                                                                 'required': ['request_id',
                                                                              'project_id',
                                                                              'project_context_revision_id',
                                                                              'expected_api_version',
                                                                              'backtest_run_id',
                                                                              'ledger_manifest_artifact_id',
                                                                              'reconciliation_profile_id',
                                                                              'idempotency_key'],
                                                                 'properties': {'request_id': {'type': 'string',
                                                                                               'description': 'Caller-generated '
                                                                                                              'UUIDv7; '
                                                                                                              'transport '
                                                                                                              'deduplication '
                                                                                                              'only',
                                                                                               'format': 'uuid'},
                                                                                'project_id': {'type': 'string',
                                                                                               'description': 'Stable '
                                                                                                              'project '
                                                                                                              'identity',
                                                                                               'pattern': '^prj_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                'project_context_revision_id': {'type': 'string',
                                                                                                                'description': 'Immutable '
                                                                                                                               'project-context '
                                                                                                                               'revision '
                                                                                                                               'identity',
                                                                                                                'pattern': '^pcr_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                'expected_api_version': {'type': 'string',
                                                                                                         'description': 'Exact '
                                                                                                                        'ASL '
                                                                                                                        'major.minor '
                                                                                                                        'contract '
                                                                                                                        'expected '
                                                                                                                        'by '
                                                                                                                        'caller',
                                                                                                         'const': '1.0'},
                                                                                'backtest_run_id': {'type': 'string',
                                                                                                    'description': 'Immutable '
                                                                                                                   'financial-input '
                                                                                                                   'run '
                                                                                                                   'identity',
                                                                                                    'pattern': '^run_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                'ledger_manifest_artifact_id': {'type': 'string',
                                                                                                                'description': 'Content-addressed '
                                                                                                                               'artifact '
                                                                                                                               'identity',
                                                                                                                'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                'reconciliation_profile_id': {'type': 'string',
                                                                                                              'description': 'Pinned '
                                                                                                                             'accounting '
                                                                                                                             'tolerances'},
                                                                                'idempotency_key': {'type': 'string',
                                                                                                    'description': 'Stable '
                                                                                                                   'reconcile '
                                                                                                                   'key'}}}},
                                      'response_dto': {'name': 'ReconcileLedgerAcceptedV1',
                                                       'schema': {'type': 'object',
                                                                  'additionalProperties': False,
                                                                  'required': ['request_id',
                                                                               'task_id',
                                                                               'run_id',
                                                                               'accepted_state'],
                                                                  'properties': {'request_id': {'type': 'string',
                                                                                                'description': 'Echoed '
                                                                                                               'request '
                                                                                                               'identity',
                                                                                                'format': 'uuid'},
                                                                                 'task_id': {'type': 'string',
                                                                                             'description': 'Durable '
                                                                                                            'user-work '
                                                                                                            'identity',
                                                                                             'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                 'run_id': {'type': 'string',
                                                                                            'description': 'Immutable '
                                                                                                           'financial-input '
                                                                                                           'run '
                                                                                                           'identity',
                                                                                            'pattern': '^run_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                 'accepted_state': {'type': 'string',
                                                                                                    'description': 'Persisted '
                                                                                                                   'acceptance '
                                                                                                                   'state',
                                                                                                    'const': 'QUEUED'},
                                                                                 'event_cursor': {'type': 'integer',
                                                                                                  'description': 'First '
                                                                                                                 'durable '
                                                                                                                 'event '
                                                                                                                 'sequence',
                                                                                                  'minimum': 1}}}},
                                      'idempotency': {'mode': 'REQUEST_ID',
                                                      'scope': 'operation_id + project_id + '
                                                               'idempotency_key/request_id',
                                                      'same_key_same_canonical_request': 'return_original_outcome',
                                                      'same_key_different_canonical_request': 'IDEMPOTENCY_CONFLICT'},
                                      'async_behavior': {'creates_task_run': True,
                                                         'run_identity_inputs': ['ledger hashes',
                                                                                 'rules',
                                                                                 'reconciliation '
                                                                                 'profile'],
                                                         'artifact_outputs': ['LedgerReconciliationReport'],
                                                         'cancel': 'COOPERATIVE',
                                                         'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                         'resume': 'FROM_DATE_CHECKPOINT',
                                                         'input_change': 'MUST_CREATE_NEW_RUN',
                                                         'attempt_rule': 'retry/resume always '
                                                                         'creates a new '
                                                                         'TaskAttempt; previous '
                                                                         'attempts are immutable'},
                                      'truth_pit_preconditions': ['orders, fills, positions, cash, '
                                                                  'fees and NAV all present'],
                                      'errors': ['INVALID_ARGUMENT',
                                                 'VERSION_MISMATCH',
                                                 'NOT_FOUND',
                                                 'CONFLICT',
                                                 'IDEMPOTENCY_CONFLICT',
                                                 'CAPABILITY_UNAVAILABLE',
                                                 'TRUTH_PRECONDITION_FAILED',
                                                 'PIT_UNPROVABLE',
                                                 'ARTIFACT_NOT_PUBLISHED',
                                                 'RESOURCE_REJECTED',
                                                 'INTERNAL_ERROR',
                                                 'LEDGER_UNRECONCILED'],
                                      'provenance_required': ['request_actor',
                                                              'project_context_revision_id',
                                                              'operation_id',
                                                              'contract_version',
                                                              'input_object_ids',
                                                              'input_content_hashes',
                                                              'environment_profile_id',
                                                              'code_version'],
                                      'read_models': [],
                                      'frontend_capabilities': ['orders/fills/positions/cash']},
 'ResultService.v1.finalizeResult': {'operation_id': 'ResultService.v1.finalizeResult',
                                     'version': '1.0.0',
                                     'kind': 'ASYNC_COMMAND',
                                     'request_dto': {'name': 'FinalizeResultRequestV1',
                                                     'schema': {'type': 'object',
                                                                'additionalProperties': False,
                                                                'required': ['request_id',
                                                                             'project_id',
                                                                             'project_context_revision_id',
                                                                             'expected_api_version',
                                                                             'backtest_run_id',
                                                                             'reconciliation_artifact_id',
                                                                             'analytics_spec',
                                                                             'idempotency_key'],
                                                                'properties': {'request_id': {'type': 'string',
                                                                                              'description': 'Caller-generated '
                                                                                                             'UUIDv7; '
                                                                                                             'transport '
                                                                                                             'deduplication '
                                                                                                             'only',
                                                                                              'format': 'uuid'},
                                                                               'project_id': {'type': 'string',
                                                                                              'description': 'Stable '
                                                                                                             'project '
                                                                                                             'identity',
                                                                                              'pattern': '^prj_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                               'project_context_revision_id': {'type': 'string',
                                                                                                               'description': 'Immutable '
                                                                                                                              'project-context '
                                                                                                                              'revision '
                                                                                                                              'identity',
                                                                                                               'pattern': '^pcr_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                               'expected_api_version': {'type': 'string',
                                                                                                        'description': 'Exact '
                                                                                                                       'ASL '
                                                                                                                       'major.minor '
                                                                                                                       'contract '
                                                                                                                       'expected '
                                                                                                                       'by '
                                                                                                                       'caller',
                                                                                                        'const': '1.0'},
                                                                               'backtest_run_id': {'type': 'string',
                                                                                                   'description': 'Immutable '
                                                                                                                  'financial-input '
                                                                                                                  'run '
                                                                                                                  'identity',
                                                                                                   'pattern': '^run_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                               'reconciliation_artifact_id': {'type': 'string',
                                                                                                              'description': 'Content-addressed '
                                                                                                                             'artifact '
                                                                                                                             'identity',
                                                                                                              'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                               'analytics_spec': {'type': 'object',
                                                                                                  'description': 'Metrics, '
                                                                                                                 'attribution, '
                                                                                                                 'walk-forward '
                                                                                                                 'and '
                                                                                                                 'sensitivity '
                                                                                                                 'selections'},
                                                                               'idempotency_key': {'type': 'string',
                                                                                                   'description': 'Stable '
                                                                                                                  'finalization '
                                                                                                                  'key'}}}},
                                     'response_dto': {'name': 'FinalizeResultAcceptedV1',
                                                      'schema': {'type': 'object',
                                                                 'additionalProperties': False,
                                                                 'required': ['request_id',
                                                                              'task_id',
                                                                              'run_id',
                                                                              'accepted_state'],
                                                                 'properties': {'request_id': {'type': 'string',
                                                                                               'description': 'Echoed '
                                                                                                              'request '
                                                                                                              'identity',
                                                                                               'format': 'uuid'},
                                                                                'task_id': {'type': 'string',
                                                                                            'description': 'Durable '
                                                                                                           'user-work '
                                                                                                           'identity',
                                                                                            'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                'run_id': {'type': 'string',
                                                                                           'description': 'Immutable '
                                                                                                          'financial-input '
                                                                                                          'run '
                                                                                                          'identity',
                                                                                           'pattern': '^run_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                'accepted_state': {'type': 'string',
                                                                                                   'description': 'Persisted '
                                                                                                                  'acceptance '
                                                                                                                  'state',
                                                                                                   'const': 'QUEUED'},
                                                                                'event_cursor': {'type': 'integer',
                                                                                                 'description': 'First '
                                                                                                                'durable '
                                                                                                                'event '
                                                                                                                'sequence',
                                                                                                 'minimum': 1}}}},
                                     'idempotency': {'mode': 'REQUEST_ID',
                                                     'scope': 'operation_id + project_id + '
                                                              'idempotency_key/request_id',
                                                     'same_key_same_canonical_request': 'return_original_outcome',
                                                     'same_key_different_canonical_request': 'IDEMPOTENCY_CONFLICT'},
                                     'async_behavior': {'creates_task_run': True,
                                                        'run_identity_inputs': ['backtest run',
                                                                                'reconciled ledger',
                                                                                'benchmark',
                                                                                'analytics spec'],
                                                        'artifact_outputs': ['ResultSeriesParquet',
                                                                             'ResultMetrics',
                                                                             'AttributionParquet',
                                                                             'AnalysisDiagnostics'],
                                                        'cancel': 'COOPERATIVE',
                                                        'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                        'resume': 'FROM_ANALYSIS_CHECKPOINT',
                                                        'input_change': 'MUST_CREATE_NEW_RUN',
                                                        'attempt_rule': 'retry/resume always '
                                                                        'creates a new '
                                                                        'TaskAttempt; previous '
                                                                        'attempts are immutable'},
                                     'truth_pit_preconditions': ['reconciliation PASS is mandatory '
                                                                 'for VALID Result',
                                                                 'benchmark snapshot compatible'],
                                     'errors': ['INVALID_ARGUMENT',
                                                'VERSION_MISMATCH',
                                                'NOT_FOUND',
                                                'CONFLICT',
                                                'IDEMPOTENCY_CONFLICT',
                                                'CAPABILITY_UNAVAILABLE',
                                                'TRUTH_PRECONDITION_FAILED',
                                                'PIT_UNPROVABLE',
                                                'ARTIFACT_NOT_PUBLISHED',
                                                'RESOURCE_REJECTED',
                                                'INTERNAL_ERROR'],
                                     'provenance_required': ['request_actor',
                                                             'project_context_revision_id',
                                                             'operation_id',
                                                             'contract_version',
                                                             'input_object_ids',
                                                             'input_content_hashes',
                                                             'environment_profile_id',
                                                             'code_version'],
                                     'read_models': [],
                                     'frontend_capabilities': ['Result performance',
                                                               'attribution',
                                                               'walk-forward',
                                                               'sensitivity']},
 'ResultService.v1.getResult': {'operation_id': 'ResultService.v1.getResult',
                                'version': '1.0.0',
                                'kind': 'QUERY',
                                'request_dto': {'name': 'GetResultRequestV1',
                                                'schema': {'type': 'object',
                                                           'additionalProperties': False,
                                                           'required': ['request_id',
                                                                        'project_id',
                                                                        'project_context_revision_id',
                                                                        'expected_api_version',
                                                                        'result_id',
                                                                        'section',
                                                                        'page'],
                                                           'properties': {'request_id': {'type': 'string',
                                                                                         'description': 'Caller-generated '
                                                                                                        'UUIDv7; '
                                                                                                        'transport '
                                                                                                        'deduplication '
                                                                                                        'only',
                                                                                         'format': 'uuid'},
                                                                          'project_id': {'type': 'string',
                                                                                         'description': 'Stable '
                                                                                                        'project '
                                                                                                        'identity',
                                                                                         'pattern': '^prj_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                          'project_context_revision_id': {'type': 'string',
                                                                                                          'description': 'Immutable '
                                                                                                                         'project-context '
                                                                                                                         'revision '
                                                                                                                         'identity',
                                                                                                          'pattern': '^pcr_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                          'expected_api_version': {'type': 'string',
                                                                                                   'description': 'Exact '
                                                                                                                  'ASL '
                                                                                                                  'major.minor '
                                                                                                                  'contract '
                                                                                                                  'expected '
                                                                                                                  'by '
                                                                                                                  'caller',
                                                                                                   'const': '1.0'},
                                                                          'result_id': {'type': 'string',
                                                                                        'description': 'Result '
                                                                                                       'identity'},
                                                                          'section': {'type': 'string',
                                                                                      'description': 'Requested '
                                                                                                     'paged/downsampled '
                                                                                                     'section'},
                                                                          'page': {'type': 'object',
                                                                                   'description': 'Cursor '
                                                                                                  'and '
                                                                                                  'bounded '
                                                                                                  'page '
                                                                                                  'size'}}}},
                                'response_dto': {'name': 'GetResultResponseV1',
                                                 'schema': {'type': 'object',
                                                            'additionalProperties': False,
                                                            'required': ['request_id',
                                                                         'truth_state',
                                                                         'read_model'],
                                                            'properties': {'request_id': {'type': 'string',
                                                                                          'description': 'Echoed '
                                                                                                         'request '
                                                                                                         'identity',
                                                                                          'format': 'uuid'},
                                                                           'truth_state': {'type': 'string',
                                                                                           'description': 'Explicit '
                                                                                                          'capability '
                                                                                                          'truth',
                                                                                           'enum': ['FORMAL',
                                                                                                    'DEMO',
                                                                                                    'UNAVAILABLE']},
                                                                           'read_model': {'type': 'object',
                                                                                          'description': 'Small '
                                                                                                         'JSON '
                                                                                                         'ResultReadModelV1; '
                                                                                                         'any '
                                                                                                         'large '
                                                                                                         'table '
                                                                                                         'is '
                                                                                                         'an '
                                                                                                         'ArtifactRef'}}}},
                                'idempotency': {'mode': 'REQUEST_ID',
                                                'scope': 'operation_id + project_id + '
                                                         'idempotency_key/request_id',
                                                'same_key_same_canonical_request': 'return_original_outcome',
                                                'same_key_different_canonical_request': 'IDEMPOTENCY_CONFLICT'},
                                'async_behavior': {'creates_task_run': False,
                                                   'run_identity_inputs': [],
                                                   'artifact_outputs': [],
                                                   'cancel': 'NOT_APPLICABLE',
                                                   'retry': 'NOT_APPLICABLE',
                                                   'resume': 'NOT_APPLICABLE',
                                                   'input_change': 'NOT_APPLICABLE',
                                                   'attempt_rule': 'NOT_APPLICABLE'},
                                'truth_pit_preconditions': ['ProjectContextRevision exists and is '
                                                            'not superseded for this request'],
                                'errors': ['INVALID_ARGUMENT',
                                           'VERSION_MISMATCH',
                                           'NOT_FOUND',
                                           'CONFLICT',
                                           'IDEMPOTENCY_CONFLICT',
                                           'CAPABILITY_UNAVAILABLE',
                                           'TRUTH_PRECONDITION_FAILED',
                                           'PIT_UNPROVABLE',
                                           'ARTIFACT_NOT_PUBLISHED',
                                           'RESOURCE_REJECTED',
                                           'INTERNAL_ERROR'],
                                'provenance_required': ['request_actor',
                                                        'project_context_revision_id',
                                                        'operation_id',
                                                        'contract_version',
                                                        'input_object_ids',
                                                        'input_content_hashes',
                                                        'environment_profile_id',
                                                        'code_version'],
                                'read_models': ['ResultReadModelV1'],
                                'frontend_capabilities': ['Result Lab',
                                                          'paged ledger',
                                                          'chart series']},
 'ResultService.v1.compareResults': {'operation_id': 'ResultService.v1.compareResults',
                                     'version': '1.0.0',
                                     'kind': 'QUERY',
                                     'request_dto': {'name': 'CompareResultsRequestV1',
                                                     'schema': {'type': 'object',
                                                                'additionalProperties': False,
                                                                'required': ['request_id',
                                                                             'project_id',
                                                                             'project_context_revision_id',
                                                                             'expected_api_version',
                                                                             'result_ids',
                                                                             'comparison_spec'],
                                                                'properties': {'request_id': {'type': 'string',
                                                                                              'description': 'Caller-generated '
                                                                                                             'UUIDv7; '
                                                                                                             'transport '
                                                                                                             'deduplication '
                                                                                                             'only',
                                                                                              'format': 'uuid'},
                                                                               'project_id': {'type': 'string',
                                                                                              'description': 'Stable '
                                                                                                             'project '
                                                                                                             'identity',
                                                                                              'pattern': '^prj_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                               'project_context_revision_id': {'type': 'string',
                                                                                                               'description': 'Immutable '
                                                                                                                              'project-context '
                                                                                                                              'revision '
                                                                                                                              'identity',
                                                                                                               'pattern': '^pcr_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                               'expected_api_version': {'type': 'string',
                                                                                                        'description': 'Exact '
                                                                                                                       'ASL '
                                                                                                                       'major.minor '
                                                                                                                       'contract '
                                                                                                                       'expected '
                                                                                                                       'by '
                                                                                                                       'caller',
                                                                                                        'const': '1.0'},
                                                                               'result_ids': {'type': 'array',
                                                                                              'description': 'Comparable '
                                                                                                             'results',
                                                                                              'items': {'type': 'string'},
                                                                                              'minItems': 2},
                                                                               'comparison_spec': {'type': 'object',
                                                                                                   'description': 'Alignment '
                                                                                                                  'and '
                                                                                                                  'metric '
                                                                                                                  'choices'}}}},
                                     'response_dto': {'name': 'CompareResultsResponseV1',
                                                      'schema': {'type': 'object',
                                                                 'additionalProperties': False,
                                                                 'required': ['request_id',
                                                                              'truth_state',
                                                                              'read_model'],
                                                                 'properties': {'request_id': {'type': 'string',
                                                                                               'description': 'Echoed '
                                                                                                              'request '
                                                                                                              'identity',
                                                                                               'format': 'uuid'},
                                                                                'truth_state': {'type': 'string',
                                                                                                'description': 'Explicit '
                                                                                                               'capability '
                                                                                                               'truth',
                                                                                                'enum': ['FORMAL',
                                                                                                         'DEMO',
                                                                                                         'UNAVAILABLE']},
                                                                                'read_model': {'type': 'object',
                                                                                               'description': 'Small '
                                                                                                              'JSON '
                                                                                                              'ResultComparisonReadModelV1; '
                                                                                                              'any '
                                                                                                              'large '
                                                                                                              'table '
                                                                                                              'is '
                                                                                                              'an '
                                                                                                              'ArtifactRef'}}}},
                                     'idempotency': {'mode': 'REQUEST_ID',
                                                     'scope': 'operation_id + project_id + '
                                                              'idempotency_key/request_id',
                                                     'same_key_same_canonical_request': 'return_original_outcome',
                                                     'same_key_different_canonical_request': 'IDEMPOTENCY_CONFLICT'},
                                     'async_behavior': {'creates_task_run': False,
                                                        'run_identity_inputs': [],
                                                        'artifact_outputs': [],
                                                        'cancel': 'NOT_APPLICABLE',
                                                        'retry': 'NOT_APPLICABLE',
                                                        'resume': 'NOT_APPLICABLE',
                                                        'input_change': 'NOT_APPLICABLE',
                                                        'attempt_rule': 'NOT_APPLICABLE'},
                                     'truth_pit_preconditions': ['ProjectContextRevision exists '
                                                                 'and is not superseded for this '
                                                                 'request'],
                                     'errors': ['INVALID_ARGUMENT',
                                                'VERSION_MISMATCH',
                                                'NOT_FOUND',
                                                'CONFLICT',
                                                'IDEMPOTENCY_CONFLICT',
                                                'CAPABILITY_UNAVAILABLE',
                                                'TRUTH_PRECONDITION_FAILED',
                                                'PIT_UNPROVABLE',
                                                'ARTIFACT_NOT_PUBLISHED',
                                                'RESOURCE_REJECTED',
                                                'INTERNAL_ERROR'],
                                     'provenance_required': ['request_actor',
                                                             'project_context_revision_id',
                                                             'operation_id',
                                                             'contract_version',
                                                             'input_object_ids',
                                                             'input_content_hashes',
                                                             'environment_profile_id',
                                                             'code_version'],
                                     'read_models': ['ResultComparisonReadModelV1'],
                                     'frontend_capabilities': ['result comparison', 'lineage']}}

class ReconcileLedgerRequestV1(ClosedDto):
    DTO_NAME = 'ReconcileLedgerRequestV1'
    OPERATION_ID = 'ResultService.v1.reconcileLedger'
    SCHEMA = METHOD_SPECS['ResultService.v1.reconcileLedger']['request_dto']['schema']

class ReconcileLedgerAcceptedV1(ClosedDto):
    DTO_NAME = 'ReconcileLedgerAcceptedV1'
    OPERATION_ID = 'ResultService.v1.reconcileLedger'
    SCHEMA = METHOD_SPECS['ResultService.v1.reconcileLedger']['response_dto']['schema']

class FinalizeResultRequestV1(ClosedDto):
    DTO_NAME = 'FinalizeResultRequestV1'
    OPERATION_ID = 'ResultService.v1.finalizeResult'
    SCHEMA = METHOD_SPECS['ResultService.v1.finalizeResult']['request_dto']['schema']

class FinalizeResultAcceptedV1(ClosedDto):
    DTO_NAME = 'FinalizeResultAcceptedV1'
    OPERATION_ID = 'ResultService.v1.finalizeResult'
    SCHEMA = METHOD_SPECS['ResultService.v1.finalizeResult']['response_dto']['schema']

class GetResultRequestV1(ClosedDto):
    DTO_NAME = 'GetResultRequestV1'
    OPERATION_ID = 'ResultService.v1.getResult'
    SCHEMA = METHOD_SPECS['ResultService.v1.getResult']['request_dto']['schema']

class GetResultResponseV1(ClosedDto):
    DTO_NAME = 'GetResultResponseV1'
    OPERATION_ID = 'ResultService.v1.getResult'
    SCHEMA = METHOD_SPECS['ResultService.v1.getResult']['response_dto']['schema']

class CompareResultsRequestV1(ClosedDto):
    DTO_NAME = 'CompareResultsRequestV1'
    OPERATION_ID = 'ResultService.v1.compareResults'
    SCHEMA = METHOD_SPECS['ResultService.v1.compareResults']['request_dto']['schema']

class CompareResultsResponseV1(ClosedDto):
    DTO_NAME = 'CompareResultsResponseV1'
    OPERATION_ID = 'ResultService.v1.compareResults'
    SCHEMA = METHOD_SPECS['ResultService.v1.compareResults']['response_dto']['schema']

OPERATION_IDS = ('ResultService.v1.reconcileLedger',
 'ResultService.v1.finalizeResult',
 'ResultService.v1.getResult',
 'ResultService.v1.compareResults')
OPERATIONS = (
    OperationContract(
        operation_id='ResultService.v1.reconcileLedger',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=ReconcileLedgerRequestV1,
        response_type=ReconcileLedgerAcceptedV1,
        metadata=METHOD_SPECS['ResultService.v1.reconcileLedger'],
    ),
    OperationContract(
        operation_id='ResultService.v1.finalizeResult',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=FinalizeResultRequestV1,
        response_type=FinalizeResultAcceptedV1,
        metadata=METHOD_SPECS['ResultService.v1.finalizeResult'],
    ),
    OperationContract(
        operation_id='ResultService.v1.getResult',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetResultRequestV1,
        response_type=GetResultResponseV1,
        metadata=METHOD_SPECS['ResultService.v1.getResult'],
    ),
    OperationContract(
        operation_id='ResultService.v1.compareResults',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=CompareResultsRequestV1,
        response_type=CompareResultsResponseV1,
        metadata=METHOD_SPECS['ResultService.v1.compareResults'],
    ),
)
CONTRACT = ServiceContract(
    contract_id=CONTRACT_ID,
    service=SERVICE,
    api_version=API_VERSION,
    operations=OPERATIONS,
)

__all__ = ('CONTRACT_ID',
 'SERVICE',
 'API_VERSION',
 'OPERATION_IDS',
 'OPERATIONS',
 'CONTRACT',
 'ReconcileLedgerRequestV1',
 'ReconcileLedgerAcceptedV1',
 'FinalizeResultRequestV1',
 'FinalizeResultAcceptedV1',
 'GetResultRequestV1',
 'GetResultResponseV1',
 'CompareResultsRequestV1',
 'CompareResultsResponseV1')

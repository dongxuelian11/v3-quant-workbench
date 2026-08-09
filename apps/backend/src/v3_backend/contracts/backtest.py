from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:backtest:1.0.0'
SERVICE = 'BacktestService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'BacktestService.v1.createExperiment': {'operation_id': 'BacktestService.v1.createExperiment',
                                         'version': '1.0.0',
                                         'kind': 'COMMAND',
                                         'request_dto': {'name': 'CreateExperimentRequestV1',
                                                         'schema': {'type': 'object',
                                                                    'additionalProperties': False,
                                                                    'required': ['request_id',
                                                                                 'project_id',
                                                                                 'project_context_revision_id',
                                                                                 'expected_api_version',
                                                                                 'experiment_spec',
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
                                                                                   'experiment_spec': {'type': 'object',
                                                                                                       'description': 'Matrix '
                                                                                                                      'axes '
                                                                                                                      'and '
                                                                                                                      'pinned '
                                                                                                                      'base '
                                                                                                                      'RunSpec '
                                                                                                                      'inputs'},
                                                                                   'idempotency_key': {'type': 'string',
                                                                                                       'description': 'Stable '
                                                                                                                      'experiment '
                                                                                                                      'key'}}}},
                                         'response_dto': {'name': 'CreateExperimentResponseV1',
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
                                                                                                                  'ExperimentReadModelV1; '
                                                                                                                  'any '
                                                                                                                  'large '
                                                                                                                  'table '
                                                                                                                  'is '
                                                                                                                  'an '
                                                                                                                  'ArtifactRef'}}}},
                                         'idempotency': {'mode': 'IDEMPOTENCY_KEY',
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
                                         'truth_pit_preconditions': ['matrix finite and within '
                                                                     'quota',
                                                                     'all financial identities are '
                                                                     'version-pinned'],
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
                                         'read_models': ['ExperimentReadModelV1'],
                                         'frontend_capabilities': ['Backtest matrix']},
 'BacktestService.v1.expandExperiment': {'operation_id': 'BacktestService.v1.expandExperiment',
                                         'version': '1.0.0',
                                         'kind': 'ASYNC_COMMAND',
                                         'request_dto': {'name': 'ExpandExperimentRequestV1',
                                                         'schema': {'type': 'object',
                                                                    'additionalProperties': False,
                                                                    'required': ['request_id',
                                                                                 'project_id',
                                                                                 'project_context_revision_id',
                                                                                 'expected_api_version',
                                                                                 'experiment_id',
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
                                                                                   'experiment_id': {'type': 'string',
                                                                                                     'description': 'Persisted '
                                                                                                                    'experiment'},
                                                                                   'idempotency_key': {'type': 'string',
                                                                                                       'description': 'Stable '
                                                                                                                      'expansion '
                                                                                                                      'key'}}}},
                                         'response_dto': {'name': 'ExpandExperimentAcceptedV1',
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
                                                            'run_identity_inputs': ['experiment '
                                                                                    'spec hash'],
                                                            'artifact_outputs': ['ExperimentExpansionManifest'],
                                                            'cancel': 'COOPERATIVE',
                                                            'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                            'resume': 'FROM_AXIS_CHECKPOINT',
                                                            'input_change': 'MUST_CREATE_NEW_RUN',
                                                            'attempt_rule': 'retry/resume always '
                                                                            'creates a new '
                                                                            'TaskAttempt; previous '
                                                                            'attempts are '
                                                                            'immutable'},
                                         'truth_pit_preconditions': ['each matrix cell becomes an '
                                                                     'independent child Task/Run',
                                                                     'batch may become PARTIAL'],
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
                                         'frontend_capabilities': ['batch queue']},
 'BacktestService.v1.submitBacktest': {'operation_id': 'BacktestService.v1.submitBacktest',
                                       'version': '1.0.0',
                                       'kind': 'ASYNC_COMMAND',
                                       'request_dto': {'name': 'SubmitBacktestRequestV1',
                                                       'schema': {'type': 'object',
                                                                  'additionalProperties': False,
                                                                  'required': ['request_id',
                                                                               'project_id',
                                                                               'project_context_revision_id',
                                                                               'expected_api_version',
                                                                               'run_spec_id',
                                                                               'execution_adapter_version_id',
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
                                                                                 'run_spec_id': {'type': 'string',
                                                                                                 'description': 'Immutable '
                                                                                                                'V3-owned '
                                                                                                                'RunSpec'},
                                                                                 'execution_adapter_version_id': {'type': 'string',
                                                                                                                  'description': 'Explicit '
                                                                                                                                 'admitted '
                                                                                                                                 'engine; '
                                                                                                                                 'only '
                                                                                                                                 'one '
                                                                                                                                 'FORMAL '
                                                                                                                                 'engine '
                                                                                                                                 'active'},
                                                                                 'idempotency_key': {'type': 'string',
                                                                                                     'description': 'Stable '
                                                                                                                    'submit '
                                                                                                                    'key'}}}},
                                       'response_dto': {'name': 'SubmitBacktestAcceptedV1',
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
                                                          'run_identity_inputs': ['RunSpec hash',
                                                                                  'strategy',
                                                                                  'snapshot',
                                                                                  'universe',
                                                                                  'portfolio',
                                                                                  'risk/optimization '
                                                                                  'if used',
                                                                                  'fee/rule '
                                                                                  'profiles',
                                                                                  'engine version',
                                                                                  'environment'],
                                                          'artifact_outputs': ['StandardLedgerParquetSet',
                                                                               'ExecutionDiagnostics',
                                                                               'Checkpoint'],
                                                          'cancel': 'CHECKPOINT_THEN_COOPERATIVE_TERMINATE',
                                                          'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                          'resume': 'FROM_COMPATIBLE_LEDGER_CHECKPOINT',
                                                          'input_change': 'MUST_CREATE_NEW_RUN',
                                                          'attempt_rule': 'retry/resume always '
                                                                          'creates a new '
                                                                          'TaskAttempt; previous '
                                                                          'attempts are immutable'},
                                       'truth_pit_preconditions': ['execution adapter passed '
                                                                   'A-share golden tests',
                                                                   'raw prices used for matching',
                                                                   'corporate actions separate '
                                                                   'from adjustment factors',
                                                                   'T+1/lot/ST/suspension/limit/delist/fees '
                                                                   'rules pinned'],
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
                                       'frontend_capabilities': ['Backtest Lab',
                                                                 'batch execution']},
 'BacktestService.v1.getExperiment': {'operation_id': 'BacktestService.v1.getExperiment',
                                      'version': '1.0.0',
                                      'kind': 'QUERY',
                                      'request_dto': {'name': 'GetExperimentRequestV1',
                                                      'schema': {'type': 'object',
                                                                 'additionalProperties': False,
                                                                 'required': ['request_id',
                                                                              'project_id',
                                                                              'project_context_revision_id',
                                                                              'expected_api_version',
                                                                              'experiment_id'],
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
                                                                                'experiment_id': {'type': 'string',
                                                                                                  'description': 'Experiment '
                                                                                                                 'identity'}}}},
                                      'response_dto': {'name': 'GetExperimentResponseV1',
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
                                                                                                               'ExperimentReadModelV1; '
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
                                      'read_models': ['ExperimentReadModelV1'],
                                      'frontend_capabilities': ['Backtest matrix progress']}}

class CreateExperimentRequestV1(ClosedDto):
    DTO_NAME = 'CreateExperimentRequestV1'
    OPERATION_ID = 'BacktestService.v1.createExperiment'
    SCHEMA = METHOD_SPECS['BacktestService.v1.createExperiment']['request_dto']['schema']

class CreateExperimentResponseV1(ClosedDto):
    DTO_NAME = 'CreateExperimentResponseV1'
    OPERATION_ID = 'BacktestService.v1.createExperiment'
    SCHEMA = METHOD_SPECS['BacktestService.v1.createExperiment']['response_dto']['schema']

class ExpandExperimentRequestV1(ClosedDto):
    DTO_NAME = 'ExpandExperimentRequestV1'
    OPERATION_ID = 'BacktestService.v1.expandExperiment'
    SCHEMA = METHOD_SPECS['BacktestService.v1.expandExperiment']['request_dto']['schema']

class ExpandExperimentAcceptedV1(ClosedDto):
    DTO_NAME = 'ExpandExperimentAcceptedV1'
    OPERATION_ID = 'BacktestService.v1.expandExperiment'
    SCHEMA = METHOD_SPECS['BacktestService.v1.expandExperiment']['response_dto']['schema']

class SubmitBacktestRequestV1(ClosedDto):
    DTO_NAME = 'SubmitBacktestRequestV1'
    OPERATION_ID = 'BacktestService.v1.submitBacktest'
    SCHEMA = METHOD_SPECS['BacktestService.v1.submitBacktest']['request_dto']['schema']

class SubmitBacktestAcceptedV1(ClosedDto):
    DTO_NAME = 'SubmitBacktestAcceptedV1'
    OPERATION_ID = 'BacktestService.v1.submitBacktest'
    SCHEMA = METHOD_SPECS['BacktestService.v1.submitBacktest']['response_dto']['schema']

class GetExperimentRequestV1(ClosedDto):
    DTO_NAME = 'GetExperimentRequestV1'
    OPERATION_ID = 'BacktestService.v1.getExperiment'
    SCHEMA = METHOD_SPECS['BacktestService.v1.getExperiment']['request_dto']['schema']

class GetExperimentResponseV1(ClosedDto):
    DTO_NAME = 'GetExperimentResponseV1'
    OPERATION_ID = 'BacktestService.v1.getExperiment'
    SCHEMA = METHOD_SPECS['BacktestService.v1.getExperiment']['response_dto']['schema']

OPERATION_IDS = ('BacktestService.v1.createExperiment',
 'BacktestService.v1.expandExperiment',
 'BacktestService.v1.submitBacktest',
 'BacktestService.v1.getExperiment')
OPERATIONS = (
    OperationContract(
        operation_id='BacktestService.v1.createExperiment',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=CreateExperimentRequestV1,
        response_type=CreateExperimentResponseV1,
        metadata=METHOD_SPECS['BacktestService.v1.createExperiment'],
    ),
    OperationContract(
        operation_id='BacktestService.v1.expandExperiment',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=ExpandExperimentRequestV1,
        response_type=ExpandExperimentAcceptedV1,
        metadata=METHOD_SPECS['BacktestService.v1.expandExperiment'],
    ),
    OperationContract(
        operation_id='BacktestService.v1.submitBacktest',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=SubmitBacktestRequestV1,
        response_type=SubmitBacktestAcceptedV1,
        metadata=METHOD_SPECS['BacktestService.v1.submitBacktest'],
    ),
    OperationContract(
        operation_id='BacktestService.v1.getExperiment',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetExperimentRequestV1,
        response_type=GetExperimentResponseV1,
        metadata=METHOD_SPECS['BacktestService.v1.getExperiment'],
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
 'CreateExperimentRequestV1',
 'CreateExperimentResponseV1',
 'ExpandExperimentRequestV1',
 'ExpandExperimentAcceptedV1',
 'SubmitBacktestRequestV1',
 'SubmitBacktestAcceptedV1',
 'GetExperimentRequestV1',
 'GetExperimentResponseV1')

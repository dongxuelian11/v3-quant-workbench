from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:task:1.0.0'
SERVICE = 'TaskService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'TaskService.v1.getTask': {'operation_id': 'TaskService.v1.getTask',
                            'version': '1.0.0',
                            'kind': 'QUERY',
                            'request_dto': {'name': 'GetTaskRequestV1',
                                            'schema': {'type': 'object',
                                                       'additionalProperties': False,
                                                       'required': ['request_id',
                                                                    'project_id',
                                                                    'project_context_revision_id',
                                                                    'expected_api_version',
                                                                    'task_id'],
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
                                                                      'task_id': {'type': 'string',
                                                                                  'description': 'Durable '
                                                                                                 'user-work '
                                                                                                 'identity',
                                                                                  'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$'}}}},
                            'response_dto': {'name': 'GetTaskResponseV1',
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
                                                                                                     'TaskReadModelV1; '
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
                            'truth_pit_preconditions': ['ProjectContextRevision exists and is not '
                                                        'superseded for this request'],
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
                            'read_models': ['TaskReadModelV1'],
                            'frontend_capabilities': ['global task drawer']},
 'TaskService.v1.listTasks': {'operation_id': 'TaskService.v1.listTasks',
                              'version': '1.0.0',
                              'kind': 'QUERY',
                              'request_dto': {'name': 'ListTasksRequestV1',
                                              'schema': {'type': 'object',
                                                         'additionalProperties': False,
                                                         'required': ['request_id',
                                                                      'project_id',
                                                                      'project_context_revision_id',
                                                                      'expected_api_version',
                                                                      'filter',
                                                                      'page_size'],
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
                                                                        'filter': {'type': 'object',
                                                                                   'description': 'Project, '
                                                                                                  'service, '
                                                                                                  'state, '
                                                                                                  'time '
                                                                                                  'and '
                                                                                                  'cursor '
                                                                                                  'filters'},
                                                                        'page_size': {'type': 'integer',
                                                                                      'description': 'Bounded '
                                                                                                     'page '
                                                                                                     'size',
                                                                                      'minimum': 1,
                                                                                      'maximum': 200}}}},
                              'response_dto': {'name': 'ListTasksResponseV1',
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
                                                                                                       'TaskPageReadModelV1; '
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
                              'read_models': ['TaskPageReadModelV1'],
                              'frontend_capabilities': ['batch queue', 'global task drawer']},
 'TaskService.v1.cancelTask': {'operation_id': 'TaskService.v1.cancelTask',
                               'version': '1.0.0',
                               'kind': 'COMMAND',
                               'request_dto': {'name': 'CancelTaskRequestV1',
                                               'schema': {'type': 'object',
                                                          'additionalProperties': False,
                                                          'required': ['request_id',
                                                                       'project_id',
                                                                       'project_context_revision_id',
                                                                       'expected_api_version',
                                                                       'task_id',
                                                                       'expected_state_version',
                                                                       'reason'],
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
                                                                         'task_id': {'type': 'string',
                                                                                     'description': 'Durable '
                                                                                                    'user-work '
                                                                                                    'identity',
                                                                                     'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                         'expected_state_version': {'type': 'integer',
                                                                                                    'description': 'Optimistic '
                                                                                                                   'state '
                                                                                                                   'version',
                                                                                                    'minimum': 0},
                                                                         'reason': {'type': 'string',
                                                                                    'description': 'User-visible '
                                                                                                   'reason'}}}},
                               'response_dto': {'name': 'CancelTaskResponseV1',
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
                                                                                                        'TaskReadModelV1; '
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
                               'truth_pit_preconditions': ['terminal Task cannot be cancelled',
                                                           'cancellation is persisted before '
                                                           'worker signal'],
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
                               'read_models': ['TaskReadModelV1'],
                               'frontend_capabilities': ['cancel']},
 'TaskService.v1.retryTask': {'operation_id': 'TaskService.v1.retryTask',
                              'version': '1.0.0',
                              'kind': 'COMMAND',
                              'request_dto': {'name': 'RetryTaskRequestV1',
                                              'schema': {'type': 'object',
                                                         'additionalProperties': False,
                                                         'required': ['request_id',
                                                                      'project_id',
                                                                      'project_context_revision_id',
                                                                      'expected_api_version',
                                                                      'task_id',
                                                                      'failed_attempt_id',
                                                                      'expected_state_version'],
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
                                                                        'task_id': {'type': 'string',
                                                                                    'description': 'Durable '
                                                                                                   'user-work '
                                                                                                   'identity',
                                                                                    'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                        'failed_attempt_id': {'type': 'string',
                                                                                              'description': 'Immutable '
                                                                                                             'worker '
                                                                                                             'attempt '
                                                                                                             'identity',
                                                                                              'pattern': '^att_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                        'expected_state_version': {'type': 'integer',
                                                                                                   'description': 'Optimistic '
                                                                                                                  'state '
                                                                                                                  'version',
                                                                                                   'minimum': 0}}}},
                              'response_dto': {'name': 'RetryTaskResponseV1',
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
                                                                                                       'TaskReadModelV1; '
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
                              'truth_pit_preconditions': ['Run inputs unchanged',
                                                          'retry policy permits error category',
                                                          'new Attempt required'],
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
                              'read_models': ['TaskReadModelV1'],
                              'frontend_capabilities': ['retry']},
 'TaskService.v1.resumeTask': {'operation_id': 'TaskService.v1.resumeTask',
                               'version': '1.0.0',
                               'kind': 'COMMAND',
                               'request_dto': {'name': 'ResumeTaskRequestV1',
                                               'schema': {'type': 'object',
                                                          'additionalProperties': False,
                                                          'required': ['request_id',
                                                                       'project_id',
                                                                       'project_context_revision_id',
                                                                       'expected_api_version',
                                                                       'task_id',
                                                                       'checkpoint_artifact_id',
                                                                       'expected_state_version'],
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
                                                                         'task_id': {'type': 'string',
                                                                                     'description': 'Durable '
                                                                                                    'user-work '
                                                                                                    'identity',
                                                                                     'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                         'checkpoint_artifact_id': {'type': 'string',
                                                                                                    'description': 'Content-addressed '
                                                                                                                   'artifact '
                                                                                                                   'identity',
                                                                                                    'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                         'expected_state_version': {'type': 'integer',
                                                                                                    'description': 'Optimistic '
                                                                                                                   'state '
                                                                                                                   'version',
                                                                                                    'minimum': 0}}}},
                               'response_dto': {'name': 'ResumeTaskResponseV1',
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
                                                                                                        'TaskReadModelV1; '
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
                               'truth_pit_preconditions': ['checkpoint belongs to same Run',
                                                           'environment and code compatibility '
                                                           'exact',
                                                           'new Attempt required'],
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
                               'read_models': ['TaskReadModelV1'],
                               'frontend_capabilities': ['resume', 'checkpoint']},
 'TaskService.v1.getEvents': {'operation_id': 'TaskService.v1.getEvents',
                              'version': '1.0.0',
                              'kind': 'QUERY',
                              'request_dto': {'name': 'GetEventsRequestV1',
                                              'schema': {'type': 'object',
                                                         'additionalProperties': False,
                                                         'required': ['request_id',
                                                                      'project_id',
                                                                      'project_context_revision_id',
                                                                      'expected_api_version',
                                                                      'after_sequence',
                                                                      'limit'],
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
                                                                        'after_sequence': {'type': 'integer',
                                                                                           'description': 'Last '
                                                                                                          'durable '
                                                                                                          'sequence '
                                                                                                          'seen',
                                                                                           'minimum': 0},
                                                                        'limit': {'type': 'integer',
                                                                                  'description': 'Bounded '
                                                                                                 'replay '
                                                                                                 'count',
                                                                                  'minimum': 1,
                                                                                  'maximum': 1000}}}},
                              'response_dto': {'name': 'GetEventsResponseV1',
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
                                                                                                       'TaskEventPageV1; '
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
                              'read_models': ['TaskEventPageV1'],
                              'frontend_capabilities': ['reconnect/event replay']}}

class GetTaskRequestV1(ClosedDto):
    DTO_NAME = 'GetTaskRequestV1'
    OPERATION_ID = 'TaskService.v1.getTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.getTask']['request_dto']['schema']

class GetTaskResponseV1(ClosedDto):
    DTO_NAME = 'GetTaskResponseV1'
    OPERATION_ID = 'TaskService.v1.getTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.getTask']['response_dto']['schema']

class ListTasksRequestV1(ClosedDto):
    DTO_NAME = 'ListTasksRequestV1'
    OPERATION_ID = 'TaskService.v1.listTasks'
    SCHEMA = METHOD_SPECS['TaskService.v1.listTasks']['request_dto']['schema']

class ListTasksResponseV1(ClosedDto):
    DTO_NAME = 'ListTasksResponseV1'
    OPERATION_ID = 'TaskService.v1.listTasks'
    SCHEMA = METHOD_SPECS['TaskService.v1.listTasks']['response_dto']['schema']

class CancelTaskRequestV1(ClosedDto):
    DTO_NAME = 'CancelTaskRequestV1'
    OPERATION_ID = 'TaskService.v1.cancelTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.cancelTask']['request_dto']['schema']

class CancelTaskResponseV1(ClosedDto):
    DTO_NAME = 'CancelTaskResponseV1'
    OPERATION_ID = 'TaskService.v1.cancelTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.cancelTask']['response_dto']['schema']

class RetryTaskRequestV1(ClosedDto):
    DTO_NAME = 'RetryTaskRequestV1'
    OPERATION_ID = 'TaskService.v1.retryTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.retryTask']['request_dto']['schema']

class RetryTaskResponseV1(ClosedDto):
    DTO_NAME = 'RetryTaskResponseV1'
    OPERATION_ID = 'TaskService.v1.retryTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.retryTask']['response_dto']['schema']

class ResumeTaskRequestV1(ClosedDto):
    DTO_NAME = 'ResumeTaskRequestV1'
    OPERATION_ID = 'TaskService.v1.resumeTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.resumeTask']['request_dto']['schema']

class ResumeTaskResponseV1(ClosedDto):
    DTO_NAME = 'ResumeTaskResponseV1'
    OPERATION_ID = 'TaskService.v1.resumeTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.resumeTask']['response_dto']['schema']

class GetEventsRequestV1(ClosedDto):
    DTO_NAME = 'GetEventsRequestV1'
    OPERATION_ID = 'TaskService.v1.getEvents'
    SCHEMA = METHOD_SPECS['TaskService.v1.getEvents']['request_dto']['schema']

class GetEventsResponseV1(ClosedDto):
    DTO_NAME = 'GetEventsResponseV1'
    OPERATION_ID = 'TaskService.v1.getEvents'
    SCHEMA = METHOD_SPECS['TaskService.v1.getEvents']['response_dto']['schema']

OPERATION_IDS = ('TaskService.v1.getTask',
 'TaskService.v1.listTasks',
 'TaskService.v1.cancelTask',
 'TaskService.v1.retryTask',
 'TaskService.v1.resumeTask',
 'TaskService.v1.getEvents')
OPERATIONS = (
    OperationContract(
        operation_id='TaskService.v1.getTask',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetTaskRequestV1,
        response_type=GetTaskResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.getTask'],
    ),
    OperationContract(
        operation_id='TaskService.v1.listTasks',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ListTasksRequestV1,
        response_type=ListTasksResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.listTasks'],
    ),
    OperationContract(
        operation_id='TaskService.v1.cancelTask',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=CancelTaskRequestV1,
        response_type=CancelTaskResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.cancelTask'],
    ),
    OperationContract(
        operation_id='TaskService.v1.retryTask',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=RetryTaskRequestV1,
        response_type=RetryTaskResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.retryTask'],
    ),
    OperationContract(
        operation_id='TaskService.v1.resumeTask',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=ResumeTaskRequestV1,
        response_type=ResumeTaskResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.resumeTask'],
    ),
    OperationContract(
        operation_id='TaskService.v1.getEvents',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetEventsRequestV1,
        response_type=GetEventsResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.getEvents'],
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
 'GetTaskRequestV1',
 'GetTaskResponseV1',
 'ListTasksRequestV1',
 'ListTasksResponseV1',
 'CancelTaskRequestV1',
 'CancelTaskResponseV1',
 'RetryTaskRequestV1',
 'RetryTaskResponseV1',
 'ResumeTaskRequestV1',
 'ResumeTaskResponseV1',
 'GetEventsRequestV1',
 'GetEventsResponseV1')

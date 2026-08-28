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

# PR03 TaskControl additions deliberately reuse the existing TaskService
# authority.  They are explicit operation contracts, not a generic command
# envelope and not a second TaskControl service.
_TASK_CONTROL_COMMON_PROPERTIES = {
    'request_id': {
        'type': 'string',
        'description': 'Caller-generated UUIDv7; transport deduplication only',
        'format': 'uuid',
    },
    'project_id': {
        'type': 'string',
        'description': 'Stable project identity',
        'pattern': '^prj_[0-9A-HJKMNP-TV-Z]{26}$',
    },
    'project_context_revision_id': {
        'type': 'string',
        'description': 'Immutable project-context revision identity',
        'pattern': '^pcr_[0-9A-HJKMNP-TV-Z]{26}$',
    },
    'expected_api_version': {
        'type': 'string',
        'description': 'Exact ASL major.minor contract expected by caller',
        'const': '1.0',
    },
}
_TASK_CONTROL_RESPONSE_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['request_id', 'truth_state', 'read_model'],
    'properties': {
        'request_id': {
            'type': 'string',
            'description': 'Echoed request identity',
            'format': 'uuid',
        },
        'truth_state': {
            'type': 'string',
            'description': 'Explicit capability truth',
            'enum': ['FORMAL', 'DEMO', 'UNAVAILABLE'],
        },
        'read_model': {
            'type': 'object',
            'description': 'Bounded JSON read model; large tables are ArtifactRefs',
        },
    },
}
_TASK_CONTROL_ERRORS = [
    'INVALID_ARGUMENT',
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
]
_TASK_CONTROL_PROVENANCE = [
    'request_actor',
    'project_context_revision_id',
    'operation_id',
    'contract_version',
    'input_object_ids',
    'input_content_hashes',
    'environment_profile_id',
    'code_version',
]


def _task_control_spec(
    operation_id: str,
    request_name: str,
    response_name: str,
    kind: str,
    extra_properties: dict[str, object],
    required_extra: list[str],
    read_model: str,
    frontend_capabilities: list[str],
    truth_pit_preconditions: list[str],
) -> dict[str, object]:
    request_properties = {
        **_TASK_CONTROL_COMMON_PROPERTIES,
        **extra_properties,
    }
    return {
        'operation_id': operation_id,
        'version': '1.0.0',
        'kind': kind,
        'request_dto': {
            'name': request_name,
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'request_id',
                    'project_id',
                    'project_context_revision_id',
                    'expected_api_version',
                    *required_extra,
                ],
                'properties': request_properties,
            },
        },
        'response_dto': {
            'name': response_name,
            'schema': _TASK_CONTROL_RESPONSE_SCHEMA,
        },
        'idempotency': {
            'mode': 'REQUEST_ID',
            'scope': 'operation_id + project_id + idempotency_key/request_id',
            'same_key_same_canonical_request': 'return_original_outcome',
            'same_key_different_canonical_request': 'IDEMPOTENCY_CONFLICT',
        },
        'async_behavior': {
            'creates_task_run': False,
            'run_identity_inputs': [],
            'artifact_outputs': [],
            'cancel': 'NOT_APPLICABLE',
            'retry': 'NOT_APPLICABLE',
            'resume': 'NOT_APPLICABLE',
            'input_change': 'NOT_APPLICABLE',
            'attempt_rule': 'NOT_APPLICABLE',
        },
        'truth_pit_preconditions': truth_pit_preconditions,
        'errors': _TASK_CONTROL_ERRORS,
        'provenance_required': _TASK_CONTROL_PROVENANCE,
        'read_models': [read_model],
        'frontend_capabilities': frontend_capabilities,
    }


METHOD_SPECS.update({
    'TaskService.v1.getOperationReceipt': _task_control_spec(
        'TaskService.v1.getOperationReceipt',
        'GetOperationReceiptRequestV1',
        'GetOperationReceiptResponseV1',
        'QUERY',
        {
            'operation_receipt_id': {
                'type': 'string',
                'description': 'Durable control-operation receipt identity',
                'pattern': '^opr_[0-9A-HJKMNP-TV-Z]{26}$',
            },
        },
        ['operation_receipt_id'],
        'OperationReceiptReadModelV1',
        ['operation receipt', 'reconnect'],
        [
            'receipt belongs to the requested project',
            'receipt outcome is read from the durable control owner',
        ],
    ),
    'TaskService.v1.listQueue': _task_control_spec(
        'TaskService.v1.listQueue',
        'ListQueueRequestV1',
        'ListQueueResponseV1',
        'QUERY',
        {
            'filter': {
                'type': 'object',
                'description': 'Explicit dispatch-state and opaque cursor filters',
                'additionalProperties': False,
                'properties': {
                    'states': {
                        'type': 'array',
                        'description': 'Dispatch states to include',
                        'minItems': 1,
                        'maxItems': 4,
                        'uniqueItems': True,
                        'items': {
                            'type': 'string',
                            'enum': ['HOLD', 'READY', 'DISPATCHED', 'TERMINAL'],
                        },
                    },
                    'cursor': {
                        'type': 'string',
                        'description': 'Opaque queue cursor',
                        'minLength': 1,
                        'maxLength': 2048,
                    },
                },
            },
            'page_size': {
                'type': 'integer',
                'description': 'Bounded queue page size',
                'minimum': 1,
                'maximum': 200,
            },
        },
        ['filter', 'page_size'],
        'QueuePageReadModelV1',
        ['queue', 'global task drawer'],
        [
            'ProjectContextRevision exists and is not superseded for this request',
            'queue rows are read from the project-bound dispatch owner',
        ],
    ),
    'TaskService.v1.startQueuedTask': _task_control_spec(
        'TaskService.v1.startQueuedTask',
        'StartQueuedTaskRequestV1',
        'StartQueuedTaskResponseV1',
        'COMMAND',
        {
            'task_id': {
                'type': 'string',
                'description': 'Durable user-work identity',
                'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$',
            },
            'expected_state_version': {
                'type': 'integer',
                'description': 'Optimistic Task aggregate state version',
                'minimum': 0,
            },
            'expected_dispatch_state_version': {
                'type': 'integer',
                'description': 'Optimistic dispatch-control state version',
                'minimum': 0,
            },
        },
        ['task_id', 'expected_state_version', 'expected_dispatch_state_version'],
        'TaskReadModelV1',
        ['queue start'],
        [
            'Task is QUEUED and dispatch control is HOLD',
            'HOLD to READY uses the supplied Task and dispatch versions',
            'worker request is rebuilt from immutable Run canonical input',
        ],
    ),
    'TaskService.v1.resumeFromCheckpoint': _task_control_spec(
        'TaskService.v1.resumeFromCheckpoint',
        'ResumeFromCheckpointRequestV1',
        'ResumeFromCheckpointResponseV1',
        'COMMAND',
        {
            'task_id': {
                'type': 'string',
                'description': 'Durable user-work identity',
                'pattern': '^tsk_[0-9A-HJKMNP-TV-Z]{26}$',
            },
            'checkpoint_artifact_id': {
                'type': 'string',
                'description': 'Content-addressed checkpoint Artifact identity',
                'pattern': '^art_sha256_[0-9a-f]{64}$',
            },
            'compatibility_hash': {
                'type': 'string',
                'description': 'Exact input/code/environment/resource compatibility hash',
                'pattern': '^[0-9a-f]{64}$',
            },
            'expected_state_version': {
                'type': 'integer',
                'description': 'Optimistic Task aggregate state version',
                'minimum': 0,
            },
        },
        ['task_id', 'checkpoint_artifact_id', 'compatibility_hash', 'expected_state_version'],
        'TaskReadModelV1',
        ['resume', 'checkpoint'],
        [
            'checkpoint belongs to the active Run',
            'input/code/environment/operation/resource compatibility is exact',
            'resume requires a new Attempt and explicit user action',
        ],
    ),
})

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

class GetOperationReceiptRequestV1(ClosedDto):
    DTO_NAME = 'GetOperationReceiptRequestV1'
    OPERATION_ID = 'TaskService.v1.getOperationReceipt'
    SCHEMA = METHOD_SPECS['TaskService.v1.getOperationReceipt']['request_dto']['schema']

class GetOperationReceiptResponseV1(ClosedDto):
    DTO_NAME = 'GetOperationReceiptResponseV1'
    OPERATION_ID = 'TaskService.v1.getOperationReceipt'
    SCHEMA = METHOD_SPECS['TaskService.v1.getOperationReceipt']['response_dto']['schema']

class ListQueueRequestV1(ClosedDto):
    DTO_NAME = 'ListQueueRequestV1'
    OPERATION_ID = 'TaskService.v1.listQueue'
    SCHEMA = METHOD_SPECS['TaskService.v1.listQueue']['request_dto']['schema']

class ListQueueResponseV1(ClosedDto):
    DTO_NAME = 'ListQueueResponseV1'
    OPERATION_ID = 'TaskService.v1.listQueue'
    SCHEMA = METHOD_SPECS['TaskService.v1.listQueue']['response_dto']['schema']

class StartQueuedTaskRequestV1(ClosedDto):
    DTO_NAME = 'StartQueuedTaskRequestV1'
    OPERATION_ID = 'TaskService.v1.startQueuedTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.startQueuedTask']['request_dto']['schema']

class StartQueuedTaskResponseV1(ClosedDto):
    DTO_NAME = 'StartQueuedTaskResponseV1'
    OPERATION_ID = 'TaskService.v1.startQueuedTask'
    SCHEMA = METHOD_SPECS['TaskService.v1.startQueuedTask']['response_dto']['schema']

class ResumeFromCheckpointRequestV1(ClosedDto):
    DTO_NAME = 'ResumeFromCheckpointRequestV1'
    OPERATION_ID = 'TaskService.v1.resumeFromCheckpoint'
    SCHEMA = METHOD_SPECS['TaskService.v1.resumeFromCheckpoint']['request_dto']['schema']

class ResumeFromCheckpointResponseV1(ClosedDto):
    DTO_NAME = 'ResumeFromCheckpointResponseV1'
    OPERATION_ID = 'TaskService.v1.resumeFromCheckpoint'
    SCHEMA = METHOD_SPECS['TaskService.v1.resumeFromCheckpoint']['response_dto']['schema']

OPERATION_IDS = ('TaskService.v1.getTask',
 'TaskService.v1.listTasks',
 'TaskService.v1.cancelTask',
 'TaskService.v1.retryTask',
 'TaskService.v1.resumeTask',
 'TaskService.v1.getEvents',
 'TaskService.v1.getOperationReceipt',
 'TaskService.v1.listQueue',
 'TaskService.v1.startQueuedTask',
 'TaskService.v1.resumeFromCheckpoint')
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
    OperationContract(
        operation_id='TaskService.v1.getOperationReceipt',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetOperationReceiptRequestV1,
        response_type=GetOperationReceiptResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.getOperationReceipt'],
    ),
    OperationContract(
        operation_id='TaskService.v1.listQueue',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ListQueueRequestV1,
        response_type=ListQueueResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.listQueue'],
    ),
    OperationContract(
        operation_id='TaskService.v1.startQueuedTask',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=StartQueuedTaskRequestV1,
        response_type=StartQueuedTaskResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.startQueuedTask'],
    ),
    OperationContract(
        operation_id='TaskService.v1.resumeFromCheckpoint',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=ResumeFromCheckpointRequestV1,
        response_type=ResumeFromCheckpointResponseV1,
        metadata=METHOD_SPECS['TaskService.v1.resumeFromCheckpoint'],
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
 'GetEventsResponseV1',
 'GetOperationReceiptRequestV1',
 'GetOperationReceiptResponseV1',
 'ListQueueRequestV1',
 'ListQueueResponseV1',
 'StartQueuedTaskRequestV1',
 'StartQueuedTaskResponseV1',
 'ResumeFromCheckpointRequestV1',
 'ResumeFromCheckpointResponseV1')

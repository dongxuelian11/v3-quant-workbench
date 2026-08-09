from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:study:1.0.0'
SERVICE = 'StudyService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'StudyService.v1.createStudy': {'operation_id': 'StudyService.v1.createStudy',
                                 'version': '1.0.0',
                                 'kind': 'COMMAND',
                                 'request_dto': {'name': 'CreateStudyRequestV1',
                                                 'schema': {'type': 'object',
                                                            'additionalProperties': False,
                                                            'required': ['request_id',
                                                                         'project_id',
                                                                         'project_context_revision_id',
                                                                         'expected_api_version',
                                                                         'study_spec',
                                                                         'dataset_version_id',
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
                                                                           'study_spec': {'type': 'object',
                                                                                          'description': 'Search '
                                                                                                         'space, '
                                                                                                         'objectives, '
                                                                                                         'sampler/pruner '
                                                                                                         'adapter, '
                                                                                                         'fixed-batch '
                                                                                                         'policy '
                                                                                                         'and '
                                                                                                         'budgets'},
                                                                           'dataset_version_id': {'type': 'string',
                                                                                                  'description': 'Pinned '
                                                                                                                 'dataset'},
                                                                           'idempotency_key': {'type': 'string',
                                                                                               'description': 'Stable '
                                                                                                              'create '
                                                                                                              'key'}}}},
                                 'response_dto': {'name': 'CreateStudyResponseV1',
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
                                                                                                          'StudyReadModelV1; '
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
                                 'truth_pit_preconditions': ['final-test split is hidden from '
                                                             'Study/Trial',
                                                             'search space and fixed batch size '
                                                             'bounded'],
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
                                 'read_models': ['StudyReadModelV1'],
                                 'frontend_capabilities': ['Optuna-style Study / Trial / HPO']},
 'StudyService.v1.enqueueTrialBatch': {'operation_id': 'StudyService.v1.enqueueTrialBatch',
                                       'version': '1.0.0',
                                       'kind': 'ASYNC_COMMAND',
                                       'request_dto': {'name': 'EnqueueTrialBatchRequestV1',
                                                       'schema': {'type': 'object',
                                                                  'additionalProperties': False,
                                                                  'required': ['request_id',
                                                                               'project_id',
                                                                               'project_context_revision_id',
                                                                               'expected_api_version',
                                                                               'study_id',
                                                                               'batch_size',
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
                                                                                 'study_id': {'type': 'string',
                                                                                              'description': 'Persisted '
                                                                                                             'Study '
                                                                                                             'identity'},
                                                                                 'batch_size': {'type': 'integer',
                                                                                                'description': 'Fixed '
                                                                                                               'admitted '
                                                                                                               'batch '
                                                                                                               'size',
                                                                                                'minimum': 1,
                                                                                                'maximum': 256},
                                                                                 'idempotency_key': {'type': 'string',
                                                                                                     'description': 'Stable '
                                                                                                                    'batch '
                                                                                                                    'key'}}}},
                                       'response_dto': {'name': 'EnqueueTrialBatchAcceptedV1',
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
                                                          'run_identity_inputs': ['study spec hash',
                                                                                  'dataset hash',
                                                                                  'batch ordinal',
                                                                                  'environment '
                                                                                  'profile'],
                                                          'artifact_outputs': ['TrialMetricsParquet',
                                                                               'StudyCheckpoint',
                                                                               'StudyVisualizations'],
                                                          'cancel': 'FINISH_OR_PRUNE_ACTIVE_TRIALS_THEN_STOP',
                                                          'retry': 'FAILED_TRIALS_AS_NEW_ATTEMPTS',
                                                          'resume': 'FROM_PERSISTED_STUDY_CHECKPOINT',
                                                          'input_change': 'MUST_CREATE_NEW_RUN',
                                                          'attempt_rule': 'retry/resume always '
                                                                          'creates a new '
                                                                          'TaskAttempt; previous '
                                                                          'attempts are immutable'},
                                       'truth_pit_preconditions': ['Study state RUNNABLE',
                                                                   'resource governor grants '
                                                                   'bounded worker slots'],
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
                                       'frontend_capabilities': ['pruning',
                                                                 'parallel coordinates',
                                                                 'Pareto',
                                                                 'history/importance/relationships']},
 'StudyService.v1.pauseStudy': {'operation_id': 'StudyService.v1.pauseStudy',
                                'version': '1.0.0',
                                'kind': 'COMMAND',
                                'request_dto': {'name': 'PauseStudyRequestV1',
                                                'schema': {'type': 'object',
                                                           'additionalProperties': False,
                                                           'required': ['request_id',
                                                                        'project_id',
                                                                        'project_context_revision_id',
                                                                        'expected_api_version',
                                                                        'study_id',
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
                                                                          'study_id': {'type': 'string',
                                                                                       'description': 'Study '
                                                                                                      'identity'},
                                                                          'expected_state_version': {'type': 'integer',
                                                                                                     'description': 'Optimistic '
                                                                                                                    'state '
                                                                                                                    'version',
                                                                                                     'minimum': 0}}}},
                                'response_dto': {'name': 'PauseStudyResponseV1',
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
                                                                                                         'StudyReadModelV1; '
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
                                'read_models': ['StudyReadModelV1'],
                                'frontend_capabilities': ['pause']},
 'StudyService.v1.resumeStudy': {'operation_id': 'StudyService.v1.resumeStudy',
                                 'version': '1.0.0',
                                 'kind': 'COMMAND',
                                 'request_dto': {'name': 'ResumeStudyRequestV1',
                                                 'schema': {'type': 'object',
                                                            'additionalProperties': False,
                                                            'required': ['request_id',
                                                                         'project_id',
                                                                         'project_context_revision_id',
                                                                         'expected_api_version',
                                                                         'study_id',
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
                                                                           'study_id': {'type': 'string',
                                                                                        'description': 'Study '
                                                                                                       'identity'},
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
                                 'response_dto': {'name': 'ResumeStudyResponseV1',
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
                                                                                                          'StudyReadModelV1; '
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
                                 'truth_pit_preconditions': ['checkpoint belongs to Study and '
                                                             'environment is compatible'],
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
                                 'read_models': ['StudyReadModelV1'],
                                 'frontend_capabilities': ['resume', 'persistence-backed reload']},
 'StudyService.v1.getStudy': {'operation_id': 'StudyService.v1.getStudy',
                              'version': '1.0.0',
                              'kind': 'QUERY',
                              'request_dto': {'name': 'GetStudyRequestV1',
                                              'schema': {'type': 'object',
                                                         'additionalProperties': False,
                                                         'required': ['request_id',
                                                                      'project_id',
                                                                      'project_context_revision_id',
                                                                      'expected_api_version',
                                                                      'study_id'],
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
                                                                        'study_id': {'type': 'string',
                                                                                     'description': 'Study '
                                                                                                    'identity'}}}},
                              'response_dto': {'name': 'GetStudyResponseV1',
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
                                                                                                       'StudyReadModelV1; '
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
                              'read_models': ['StudyReadModelV1'],
                              'frontend_capabilities': ['Study detail']}}

class CreateStudyRequestV1(ClosedDto):
    DTO_NAME = 'CreateStudyRequestV1'
    OPERATION_ID = 'StudyService.v1.createStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.createStudy']['request_dto']['schema']

class CreateStudyResponseV1(ClosedDto):
    DTO_NAME = 'CreateStudyResponseV1'
    OPERATION_ID = 'StudyService.v1.createStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.createStudy']['response_dto']['schema']

class EnqueueTrialBatchRequestV1(ClosedDto):
    DTO_NAME = 'EnqueueTrialBatchRequestV1'
    OPERATION_ID = 'StudyService.v1.enqueueTrialBatch'
    SCHEMA = METHOD_SPECS['StudyService.v1.enqueueTrialBatch']['request_dto']['schema']

class EnqueueTrialBatchAcceptedV1(ClosedDto):
    DTO_NAME = 'EnqueueTrialBatchAcceptedV1'
    OPERATION_ID = 'StudyService.v1.enqueueTrialBatch'
    SCHEMA = METHOD_SPECS['StudyService.v1.enqueueTrialBatch']['response_dto']['schema']

class PauseStudyRequestV1(ClosedDto):
    DTO_NAME = 'PauseStudyRequestV1'
    OPERATION_ID = 'StudyService.v1.pauseStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.pauseStudy']['request_dto']['schema']

class PauseStudyResponseV1(ClosedDto):
    DTO_NAME = 'PauseStudyResponseV1'
    OPERATION_ID = 'StudyService.v1.pauseStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.pauseStudy']['response_dto']['schema']

class ResumeStudyRequestV1(ClosedDto):
    DTO_NAME = 'ResumeStudyRequestV1'
    OPERATION_ID = 'StudyService.v1.resumeStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.resumeStudy']['request_dto']['schema']

class ResumeStudyResponseV1(ClosedDto):
    DTO_NAME = 'ResumeStudyResponseV1'
    OPERATION_ID = 'StudyService.v1.resumeStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.resumeStudy']['response_dto']['schema']

class GetStudyRequestV1(ClosedDto):
    DTO_NAME = 'GetStudyRequestV1'
    OPERATION_ID = 'StudyService.v1.getStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.getStudy']['request_dto']['schema']

class GetStudyResponseV1(ClosedDto):
    DTO_NAME = 'GetStudyResponseV1'
    OPERATION_ID = 'StudyService.v1.getStudy'
    SCHEMA = METHOD_SPECS['StudyService.v1.getStudy']['response_dto']['schema']

OPERATION_IDS = ('StudyService.v1.createStudy',
 'StudyService.v1.enqueueTrialBatch',
 'StudyService.v1.pauseStudy',
 'StudyService.v1.resumeStudy',
 'StudyService.v1.getStudy')
OPERATIONS = (
    OperationContract(
        operation_id='StudyService.v1.createStudy',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=CreateStudyRequestV1,
        response_type=CreateStudyResponseV1,
        metadata=METHOD_SPECS['StudyService.v1.createStudy'],
    ),
    OperationContract(
        operation_id='StudyService.v1.enqueueTrialBatch',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=EnqueueTrialBatchRequestV1,
        response_type=EnqueueTrialBatchAcceptedV1,
        metadata=METHOD_SPECS['StudyService.v1.enqueueTrialBatch'],
    ),
    OperationContract(
        operation_id='StudyService.v1.pauseStudy',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=PauseStudyRequestV1,
        response_type=PauseStudyResponseV1,
        metadata=METHOD_SPECS['StudyService.v1.pauseStudy'],
    ),
    OperationContract(
        operation_id='StudyService.v1.resumeStudy',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=ResumeStudyRequestV1,
        response_type=ResumeStudyResponseV1,
        metadata=METHOD_SPECS['StudyService.v1.resumeStudy'],
    ),
    OperationContract(
        operation_id='StudyService.v1.getStudy',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetStudyRequestV1,
        response_type=GetStudyResponseV1,
        metadata=METHOD_SPECS['StudyService.v1.getStudy'],
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
 'CreateStudyRequestV1',
 'CreateStudyResponseV1',
 'EnqueueTrialBatchRequestV1',
 'EnqueueTrialBatchAcceptedV1',
 'PauseStudyRequestV1',
 'PauseStudyResponseV1',
 'ResumeStudyRequestV1',
 'ResumeStudyResponseV1',
 'GetStudyRequestV1',
 'GetStudyResponseV1')

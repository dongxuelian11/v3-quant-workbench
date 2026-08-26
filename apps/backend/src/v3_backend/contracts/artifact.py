from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:artifact:1.0.0'
SERVICE = 'ArtifactService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'ArtifactService.v1.publishArtifact': {'operation_id': 'ArtifactService.v1.publishArtifact',
                                        'version': '1.0.0',
                                        'kind': 'COMMAND',
                                        'request_dto': {'name': 'PublishArtifactRequestV1',
                                                        'schema': {'type': 'object',
                                                                   'additionalProperties': False,
                                                                   'required': ['request_id',
                                                                                'project_id',
                                                                                'project_context_revision_id',
                                                                                'expected_api_version',
                                                                                'staging_token',
                                                                                'declared_media_type',
                                                                                'declared_role',
                                                                                'expected_sha256',
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
                                                                                  'staging_token': {'type': 'string',
                                                                                                    'description': 'Backend-only '
                                                                                                                   'staging '
                                                                                                                   'handle; '
                                                                                                                   'never '
                                                                                                                   'arbitrary '
                                                                                                                   'renderer '
                                                                                                                   'path'},
                                                                                  'declared_media_type': {'type': 'string',
                                                                                                          'description': 'Allow-listed '
                                                                                                                         'MIME '
                                                                                                                         'type'},
                                                                                  'declared_role': {'type': 'string',
                                                                                                    'description': 'Semantic '
                                                                                                                   'artifact '
                                                                                                                   'role'},
                                                                                  'expected_sha256': {'type': 'string',
                                                                                                      'description': 'Expected '
                                                                                                                     'byte '
                                                                                                                     'hash',
                                                                                                      'pattern': '^[0-9a-f]{64}$'},
                                                                                  'idempotency_key': {'type': 'string',
                                                                                                      'description': 'Stable '
                                                                                                                     'publication '
                                                                                                                     'key'}}}},
                                        'response_dto': {'name': 'PublishArtifactResponseV1',
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
                                                                                                                 'ArtifactDescriptorV1; '
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
                                        'truth_pit_preconditions': ['bytes fully flushed and hash '
                                                                    'verified before atomic rename',
                                                                    'safe-format scanner passed '
                                                                    'where applicable'],
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
                                        'read_models': ['ArtifactDescriptorV1'],
                                        'frontend_capabilities': ['artifact publication']},
 'ArtifactService.v1.getArtifactDescriptor': {'operation_id': 'ArtifactService.v1.getArtifactDescriptor',
                                              'version': '1.0.0',
                                              'kind': 'QUERY',
                                              'request_dto': {'name': 'GetArtifactDescriptorRequestV1',
                                                              'schema': {'type': 'object',
                                                                         'additionalProperties': False,
                                                                         'required': ['request_id',
                                                                                      'project_id',
                                                                                      'project_context_revision_id',
                                                                                      'expected_api_version',
                                                                                      'artifact_id'],
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
                                                                                        'artifact_id': {'type': 'string',
                                                                                                        'description': 'Content-addressed '
                                                                                                                       'artifact '
                                                                                                                       'identity',
                                                                                                        'pattern': '^art_sha256_[0-9a-f]{64}$'}}}},
                                              'response_dto': {'name': 'GetArtifactDescriptorResponseV1',
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
                                                                                                                       'ArtifactDescriptorV1; '
                                                                                                                       'any '
                                                                                                                       'large '
                                                                                                                       'table '
                                                                                                                       'is '
                                                                                                                       'an '
                                                                                                                       'ArtifactRef'}}}},
                                              'idempotency': {'mode': 'REQUEST_ID',
                                                              'scope': 'operation_id + project_id '
                                                                       '+ '
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
                                              'truth_pit_preconditions': ['ProjectContextRevision '
                                                                          'exists and is not '
                                                                          'superseded for this '
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
                                              'read_models': ['ArtifactDescriptorV1'],
                                              'frontend_capabilities': ['lineage', 'downloads']},
 'ArtifactService.v1.openArtifactStream': {'operation_id': 'ArtifactService.v1.openArtifactStream',
                                           'version': '1.0.0',
                                           'kind': 'QUERY',
                                           'request_dto': {'name': 'OpenArtifactStreamRequestV1',
                                                           'schema': {'type': 'object',
                                                                      'additionalProperties': False,
                                                                      'required': ['request_id',
                                                                                   'project_id',
                                                                                   'project_context_revision_id',
                                                                                   'expected_api_version',
                                                                                   'artifact_id'],
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
                                                                                     'artifact_id': {'type': 'string',
                                                                                                     'description': 'Content-addressed '
                                                                                                                    'artifact '
                                                                                                                    'identity',
                                                                                                     'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                     'range': {'type': 'object',
                                                                                               'description': 'Optional '
                                                                                                              'bounded '
                                                                                                              'byte '
                                                                                                              'range'}}}},
                                           'response_dto': {'name': 'OpenArtifactStreamResponseV1',
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
                                                                                                                    'ArtifactStreamTicketV1; '
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
                                           'truth_pit_preconditions': ['ticket scoped, short-lived '
                                                                       'and mediated by Electron '
                                                                       'Main/backend',
                                                                       'no raw filesystem path '
                                                                       'returned'],
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
                                           'read_models': ['ArtifactStreamTicketV1'],
                                           'frontend_capabilities': ['large chart/table loading']},
 'ArtifactService.v1.exportArtifact': {'operation_id': 'ArtifactService.v1.exportArtifact',
                                       'version': '1.0.0',
                                       'kind': 'ASYNC_COMMAND',
                                       'request_dto': {'name': 'ExportArtifactRequestV1',
                                                       'schema': {'type': 'object',
                                                                  'additionalProperties': False,
                                                                  'required': ['request_id',
                                                                               'project_id',
                                                                               'project_context_revision_id',
                                                                               'expected_api_version',
                                                                               'artifact_ids',
                                                                               'export_profile_id',
                                                                               'destination_token',
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
                                                                                 'artifact_ids': {'type': 'array',
                                                                                                  'description': 'Referenced '
                                                                                                                 'immutable '
                                                                                                                 'artifacts',
                                                                                                  'items': {'type': 'string',
                                                                                                            'description': 'Content-addressed '
                                                                                                                           'artifact '
                                                                                                                           'identity',
                                                                                                            'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                                  'minItems': 1},
                                                                                 'export_profile_id': {'type': 'string',
                                                                                                       'description': 'Light '
                                                                                                                      'review '
                                                                                                                      'or '
                                                                                                                      'full '
                                                                                                                      'reproduction '
                                                                                                                      'profile'},
                                                                                 'destination_token': {'type': 'string',
                                                                                                       'description': 'Electron-main '
                                                                                                                      'authorized '
                                                                                                                      'destination '
                                                                                                                      'handle'},
                                                                                 'idempotency_key': {'type': 'string',
                                                                                                     'description': 'Stable '
                                                                                                                    'export '
                                                                                                                    'key'}}}},
                                       'response_dto': {'name': 'ExportArtifactAcceptedV1',
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
                                                          'run_identity_inputs': ['artifact hashes',
                                                                                  'export profile'],
                                                          'artifact_outputs': ['ExportManifest'],
                                                          'cancel': 'COOPERATIVE',
                                                          'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                          'resume': 'FROM_FILE_CHECKPOINT',
                                                          'input_change': 'MUST_CREATE_NEW_RUN',
                                                          'attempt_rule': 'retry/resume always '
                                                                          'creates a new '
                                                                          'TaskAttempt; previous '
                                                                          'attempts are immutable'},
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
                                       'read_models': [],
                                       'frontend_capabilities': ['export']},
 'ArtifactService.v1.planGarbageCollection': {'operation_id': 'ArtifactService.v1.planGarbageCollection',
                                              'version': '1.0.0',
                                              'kind': 'QUERY',
                                              'request_dto': {'name': 'PlanGarbageCollectionRequestV1',
                                                              'schema': {'type': 'object',
                                                                         'additionalProperties': False,
                                                                         'required': ['request_id',
                                                                                      'project_id',
                                                                                      'project_context_revision_id',
                                                                                      'expected_api_version',
                                                                                      'retention_profile_id'],
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
                                                                                        'retention_profile_id': {'type': 'string',
                                                                                                                 'description': 'Pinned '
                                                                                                                                'retention '
                                                                                                                                'and '
                                                                                                                                'grace '
                                                                                                                                'policy'}}}},
                                              'response_dto': {'name': 'PlanGarbageCollectionResponseV1',
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
                                                                                                                       'GarbageCollectionPlanV1; '
                                                                                                                       'any '
                                                                                                                       'large '
                                                                                                                       'table '
                                                                                                                       'is '
                                                                                                                       'an '
                                                                                                                       'ArtifactRef'}}}},
                                              'idempotency': {'mode': 'REQUEST_ID',
                                                              'scope': 'operation_id + project_id '
                                                                       '+ '
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
                                              'truth_pit_preconditions': ['reachability closure '
                                                                          'computed',
                                                                          'referenced artifacts '
                                                                          'excluded',
                                                                          'user confirmation '
                                                                          'required for durable '
                                                                          'artifacts'],
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
                                              'read_models': ['GarbageCollectionPlanV1'],
                                              'frontend_capabilities': ['safe cleanup']}}


def _gc_common_request_properties() -> dict[str, dict[str, str]]:
    return {
        'request_id': {'type': 'string', 'format': 'uuid'},
        'project_id': {
            'type': 'string',
            'pattern': '^prj_[0-9A-HJKMNP-TV-Z]{26}$',
        },
        'project_context_revision_id': {
            'type': 'string',
            'pattern': '^pcr_[0-9A-HJKMNP-TV-Z]{26}$',
        },
        'expected_api_version': {'type': 'string', 'const': '1.0'},
    }


def _gc_request_schema(
    name: str,
    extra_properties: dict[str, dict[str, str]],
) -> dict[str, object]:
    properties = _gc_common_request_properties()
    properties.update(extra_properties)
    return {
        'name': name,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'required': list(properties),
            'properties': properties,
        },
    }


def _gc_response_dto(name: str) -> dict[str, object]:
    return {
        'name': name,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['request_id', 'truth_state', 'read_model'],
            'properties': {
                'request_id': {'type': 'string', 'format': 'uuid'},
                'truth_state': {
                    'type': 'string',
                    'enum': ['FORMAL', 'DEMO', 'UNAVAILABLE'],
                },
                'read_model': {
                    'type': 'object',
                    'description': 'Bounded garbage-collection action receipt/read model',
                },
            },
        },
    }


def _gc_method_spec(
    operation_id: str,
    request_dto: dict[str, object],
    response_dto: dict[str, object],
) -> dict[str, object]:
    return {
        'operation_id': operation_id,
        'version': '1.0.0',
        'kind': 'COMMAND',
        'request_dto': request_dto,
        'response_dto': response_dto,
        'idempotency': {
            'mode': 'REQUEST_ID',
            'scope': 'operation_id + project_id + request_id',
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
        'truth_pit_preconditions': [
            'project context revision exists and is owned by the request project',
            'exact plan, confirmation proof, and current reachability guard match',
        ],
        'errors': [
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
        ],
        'provenance_required': [
            'request_actor',
            'project_context_revision_id',
            'operation_id',
            'contract_version',
            'input_object_ids',
            'input_content_hashes',
            'environment_profile_id',
            'code_version',
        ],
        'read_models': ['GarbageCollectionBatchV1', 'GarbageCollectionReceiptV1'],
        'frontend_capabilities': [],
    }


METHOD_SPECS.update(
    {
        'ArtifactService.v1.confirmGarbageCollection': _gc_method_spec(
            'ArtifactService.v1.confirmGarbageCollection',
            _gc_request_schema(
                'ConfirmGarbageCollectionRequestV1',
                {
                    'gc_batch_id': {
                        'type': 'string',
                        'pattern': '^gcb_[0-9A-HJKMNP-TV-Z]{26}$',
                    },
                    'plan_artifact_id': {
                        'type': 'string',
                        'pattern': '^art_sha256_[0-9a-f]{64}$',
                    },
                    'exact_artifact_ids_hash': {
                        'type': 'string',
                        'pattern': '^[0-9a-f]{64}$',
                    },
                    'confirmation_nonce': {
                        'type': 'string',
                        'minLength': 1,
                        'maxLength': 128,
                    },
                },
            ),
            _gc_response_dto('ConfirmGarbageCollectionResponseV1'),
        ),
        'ArtifactService.v1.quarantineGarbageCollection': _gc_method_spec(
            'ArtifactService.v1.quarantineGarbageCollection',
            _gc_request_schema(
                'QuarantineGarbageCollectionRequestV1',
                {
                    'gc_batch_id': {
                        'type': 'string',
                        'pattern': '^gcb_[0-9A-HJKMNP-TV-Z]{26}$',
                    },
                },
            ),
            _gc_response_dto('QuarantineGarbageCollectionResponseV1'),
        ),
        'ArtifactService.v1.restoreGarbageCollection': _gc_method_spec(
            'ArtifactService.v1.restoreGarbageCollection',
            _gc_request_schema(
                'RestoreGarbageCollectionRequestV1',
                {
                    'gc_batch_id': {
                        'type': 'string',
                        'pattern': '^gcb_[0-9A-HJKMNP-TV-Z]{26}$',
                    },
                },
            ),
            _gc_response_dto('RestoreGarbageCollectionResponseV1'),
        ),
        'ArtifactService.v1.planGarbagePurge': _gc_method_spec(
            'ArtifactService.v1.planGarbagePurge',
            _gc_request_schema(
                'PlanGarbagePurgeRequestV1',
                {
                    'quarantine_gc_batch_id': {
                        'type': 'string',
                        'pattern': '^gcb_[0-9A-HJKMNP-TV-Z]{26}$',
                    },
                },
            ),
            _gc_response_dto('PlanGarbagePurgeResponseV1'),
        ),
        'ArtifactService.v1.purgeGarbageCollection': _gc_method_spec(
            'ArtifactService.v1.purgeGarbageCollection',
            _gc_request_schema(
                'PurgeGarbageCollectionRequestV1',
                {
                    'gc_batch_id': {
                        'type': 'string',
                        'pattern': '^gcb_[0-9A-HJKMNP-TV-Z]{26}$',
                    },
                },
            ),
            _gc_response_dto('PurgeGarbageCollectionResponseV1'),
        ),
    }
)

class PublishArtifactRequestV1(ClosedDto):
    DTO_NAME = 'PublishArtifactRequestV1'
    OPERATION_ID = 'ArtifactService.v1.publishArtifact'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.publishArtifact']['request_dto']['schema']

class PublishArtifactResponseV1(ClosedDto):
    DTO_NAME = 'PublishArtifactResponseV1'
    OPERATION_ID = 'ArtifactService.v1.publishArtifact'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.publishArtifact']['response_dto']['schema']

class GetArtifactDescriptorRequestV1(ClosedDto):
    DTO_NAME = 'GetArtifactDescriptorRequestV1'
    OPERATION_ID = 'ArtifactService.v1.getArtifactDescriptor'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.getArtifactDescriptor']['request_dto']['schema']

class GetArtifactDescriptorResponseV1(ClosedDto):
    DTO_NAME = 'GetArtifactDescriptorResponseV1'
    OPERATION_ID = 'ArtifactService.v1.getArtifactDescriptor'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.getArtifactDescriptor']['response_dto']['schema']

class OpenArtifactStreamRequestV1(ClosedDto):
    DTO_NAME = 'OpenArtifactStreamRequestV1'
    OPERATION_ID = 'ArtifactService.v1.openArtifactStream'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.openArtifactStream']['request_dto']['schema']

class OpenArtifactStreamResponseV1(ClosedDto):
    DTO_NAME = 'OpenArtifactStreamResponseV1'
    OPERATION_ID = 'ArtifactService.v1.openArtifactStream'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.openArtifactStream']['response_dto']['schema']

class ExportArtifactRequestV1(ClosedDto):
    DTO_NAME = 'ExportArtifactRequestV1'
    OPERATION_ID = 'ArtifactService.v1.exportArtifact'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.exportArtifact']['request_dto']['schema']

class ExportArtifactAcceptedV1(ClosedDto):
    DTO_NAME = 'ExportArtifactAcceptedV1'
    OPERATION_ID = 'ArtifactService.v1.exportArtifact'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.exportArtifact']['response_dto']['schema']

class PlanGarbageCollectionRequestV1(ClosedDto):
    DTO_NAME = 'PlanGarbageCollectionRequestV1'
    OPERATION_ID = 'ArtifactService.v1.planGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.planGarbageCollection']['request_dto']['schema']

class PlanGarbageCollectionResponseV1(ClosedDto):
    DTO_NAME = 'PlanGarbageCollectionResponseV1'
    OPERATION_ID = 'ArtifactService.v1.planGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.planGarbageCollection']['response_dto']['schema']

class ConfirmGarbageCollectionRequestV1(ClosedDto):
    DTO_NAME = 'ConfirmGarbageCollectionRequestV1'
    OPERATION_ID = 'ArtifactService.v1.confirmGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.confirmGarbageCollection']['request_dto']['schema']

class ConfirmGarbageCollectionResponseV1(ClosedDto):
    DTO_NAME = 'ConfirmGarbageCollectionResponseV1'
    OPERATION_ID = 'ArtifactService.v1.confirmGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.confirmGarbageCollection']['response_dto']['schema']

class QuarantineGarbageCollectionRequestV1(ClosedDto):
    DTO_NAME = 'QuarantineGarbageCollectionRequestV1'
    OPERATION_ID = 'ArtifactService.v1.quarantineGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.quarantineGarbageCollection']['request_dto']['schema']

class QuarantineGarbageCollectionResponseV1(ClosedDto):
    DTO_NAME = 'QuarantineGarbageCollectionResponseV1'
    OPERATION_ID = 'ArtifactService.v1.quarantineGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.quarantineGarbageCollection']['response_dto']['schema']

class RestoreGarbageCollectionRequestV1(ClosedDto):
    DTO_NAME = 'RestoreGarbageCollectionRequestV1'
    OPERATION_ID = 'ArtifactService.v1.restoreGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.restoreGarbageCollection']['request_dto']['schema']

class RestoreGarbageCollectionResponseV1(ClosedDto):
    DTO_NAME = 'RestoreGarbageCollectionResponseV1'
    OPERATION_ID = 'ArtifactService.v1.restoreGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.restoreGarbageCollection']['response_dto']['schema']

class PlanGarbagePurgeRequestV1(ClosedDto):
    DTO_NAME = 'PlanGarbagePurgeRequestV1'
    OPERATION_ID = 'ArtifactService.v1.planGarbagePurge'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.planGarbagePurge']['request_dto']['schema']

class PlanGarbagePurgeResponseV1(ClosedDto):
    DTO_NAME = 'PlanGarbagePurgeResponseV1'
    OPERATION_ID = 'ArtifactService.v1.planGarbagePurge'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.planGarbagePurge']['response_dto']['schema']

class PurgeGarbageCollectionRequestV1(ClosedDto):
    DTO_NAME = 'PurgeGarbageCollectionRequestV1'
    OPERATION_ID = 'ArtifactService.v1.purgeGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.purgeGarbageCollection']['request_dto']['schema']

class PurgeGarbageCollectionResponseV1(ClosedDto):
    DTO_NAME = 'PurgeGarbageCollectionResponseV1'
    OPERATION_ID = 'ArtifactService.v1.purgeGarbageCollection'
    SCHEMA = METHOD_SPECS['ArtifactService.v1.purgeGarbageCollection']['response_dto']['schema']

OPERATION_IDS = ('ArtifactService.v1.publishArtifact',
 'ArtifactService.v1.getArtifactDescriptor',
 'ArtifactService.v1.openArtifactStream',
 'ArtifactService.v1.exportArtifact',
 'ArtifactService.v1.planGarbageCollection',
 'ArtifactService.v1.confirmGarbageCollection',
 'ArtifactService.v1.quarantineGarbageCollection',
 'ArtifactService.v1.restoreGarbageCollection',
 'ArtifactService.v1.planGarbagePurge',
 'ArtifactService.v1.purgeGarbageCollection')
OPERATIONS = (
    OperationContract(
        operation_id='ArtifactService.v1.publishArtifact',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=PublishArtifactRequestV1,
        response_type=PublishArtifactResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.publishArtifact'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.getArtifactDescriptor',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetArtifactDescriptorRequestV1,
        response_type=GetArtifactDescriptorResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.getArtifactDescriptor'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.openArtifactStream',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=OpenArtifactStreamRequestV1,
        response_type=OpenArtifactStreamResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.openArtifactStream'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.exportArtifact',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=ExportArtifactRequestV1,
        response_type=ExportArtifactAcceptedV1,
        metadata=METHOD_SPECS['ArtifactService.v1.exportArtifact'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.planGarbageCollection',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=PlanGarbageCollectionRequestV1,
        response_type=PlanGarbageCollectionResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.planGarbageCollection'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.confirmGarbageCollection',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=ConfirmGarbageCollectionRequestV1,
        response_type=ConfirmGarbageCollectionResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.confirmGarbageCollection'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.quarantineGarbageCollection',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=QuarantineGarbageCollectionRequestV1,
        response_type=QuarantineGarbageCollectionResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.quarantineGarbageCollection'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.restoreGarbageCollection',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=RestoreGarbageCollectionRequestV1,
        response_type=RestoreGarbageCollectionResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.restoreGarbageCollection'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.planGarbagePurge',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=PlanGarbagePurgeRequestV1,
        response_type=PlanGarbagePurgeResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.planGarbagePurge'],
    ),
    OperationContract(
        operation_id='ArtifactService.v1.purgeGarbageCollection',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=PurgeGarbageCollectionRequestV1,
        response_type=PurgeGarbageCollectionResponseV1,
        metadata=METHOD_SPECS['ArtifactService.v1.purgeGarbageCollection'],
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
 'PublishArtifactRequestV1',
 'PublishArtifactResponseV1',
 'GetArtifactDescriptorRequestV1',
 'GetArtifactDescriptorResponseV1',
 'OpenArtifactStreamRequestV1',
 'OpenArtifactStreamResponseV1',
 'ExportArtifactRequestV1',
 'ExportArtifactAcceptedV1',
 'PlanGarbageCollectionRequestV1',
 'PlanGarbageCollectionResponseV1',
 'ConfirmGarbageCollectionRequestV1',
 'ConfirmGarbageCollectionResponseV1',
 'QuarantineGarbageCollectionRequestV1',
 'QuarantineGarbageCollectionResponseV1',
 'RestoreGarbageCollectionRequestV1',
 'RestoreGarbageCollectionResponseV1',
 'PlanGarbagePurgeRequestV1',
 'PlanGarbagePurgeResponseV1',
 'PurgeGarbageCollectionRequestV1',
 'PurgeGarbageCollectionResponseV1')

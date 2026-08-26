from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:project_session:1.0.0'
SERVICE = 'ProjectSessionService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'ProjectSessionService.v1.openProject': {'operation_id': 'ProjectSessionService.v1.openProject',
                                          'version': '1.0.0',
                                          'kind': 'COMMAND',
                                          'request_dto': {'name': 'OpenProjectRequestV1',
                                                          'schema': {'type': 'object',
                                                                     'additionalProperties': False,
                                                                     'required': ['request_id',
                                                                                  'project_id',
                                                                                  'project_context_revision_id',
                                                                                  'expected_api_version',
                                                                                  'project_locator',
                                                                                  'session_id'],
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
                                                                                    'project_locator': {'type': 'string',
                                                                                                        'description': 'Opaque '
                                                                                                                       'project '
                                                                                                                       'locator; '
                                                                                                                       'never '
                                                                                                                       'a '
                                                                                                                       'renderer-readable '
                                                                                                                       'database '
                                                                                                                       'path'},
                                                                                    'session_id': {'type': 'string',
                                                                                                   'description': 'Desktop '
                                                                                                                  'session '
                                                                                                                   'UUID',
                                                                                                   'pattern': '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
                                                                                                   'format': 'uuid'}}}},
                                          'response_dto': {'name': 'OpenProjectResponseV1',
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
                                                                                                                   'ProjectContextReadModelV1; '
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
                                          'truth_pit_preconditions': ['ProjectContextRevision '
                                                                      'exists and is not '
                                                                      'superseded for this '
                                                                      'request'],
                                          'errors': ['INVALID_ARGUMENT',
                                                     'VERSION_MISMATCH',
                                                     'NOT_FOUND',
                                                     'SESSION_PROJECT_BINDING_CONFLICT',
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
                                          'read_models': ['ProjectContextReadModelV1'],
                                          'frontend_capabilities': ['Shared ProjectContext',
                                                                    'layout/session restore']},
 'ProjectSessionService.v1.getProjectContext': {'operation_id': 'ProjectSessionService.v1.getProjectContext',
                                                'version': '1.0.0',
                                                'kind': 'QUERY',
                                                'request_dto': {'name': 'GetProjectContextRequestV1',
                                                                'schema': {'type': 'object',
                                                                           'additionalProperties': False,
                                                                           'required': ['request_id',
                                                                                        'project_id',
                                                                                        'project_context_revision_id',
                                                                                        'expected_api_version'],
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
                                                                                                                   'const': '1.0'}}}},
                                                'response_dto': {'name': 'GetProjectContextResponseV1',
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
                                                                                                                         'ProjectContextReadModelV1; '
                                                                                                                         'any '
                                                                                                                         'large '
                                                                                                                         'table '
                                                                                                                         'is '
                                                                                                                         'an '
                                                                                                                         'ArtifactRef'}}}},
                                                'idempotency': {'mode': 'REQUEST_ID',
                                                                'scope': 'operation_id + '
                                                                         'project_id + '
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
                                                'read_models': ['ProjectContextReadModelV1'],
                                                'frontend_capabilities': ['all five Labs shared '
                                                                          'context']},
 'ProjectSessionService.v1.reviseProjectContext': {'operation_id': 'ProjectSessionService.v1.reviseProjectContext',
                                                   'version': '1.0.0',
                                                   'kind': 'COMMAND',
                                                   'request_dto': {'name': 'ReviseProjectContextRequestV1',
                                                                   'schema': {'type': 'object',
                                                                              'additionalProperties': False,
                                                                              'required': ['request_id',
                                                                                           'project_id',
                                                                                           'project_context_revision_id',
                                                                                           'expected_api_version',
                                                                                           'base_revision_id',
                                                                                           'patch',
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
                                                                                             'base_revision_id': {'type': 'string',
                                                                                                                  'description': 'Immutable '
                                                                                                                                 'project-context '
                                                                                                                                 'revision '
                                                                                                                                 'identity',
                                                                                                                  'pattern': '^pcr_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                             'patch': {'type': 'object',
                                                                                                       'description': 'RFC '
                                                                                                                      '6902-compatible, '
                                                                                                                      'allow-listed '
                                                                                                                      'context '
                                                                                                                      'fields '
                                                                                                                      'only'},
                                                                                             'idempotency_key': {'type': 'string',
                                                                                                                 'description': 'Stable '
                                                                                                                                'command '
                                                                                                                                'key',
                                                                                                                 'minLength': 8}}}},
                                                   'response_dto': {'name': 'ReviseProjectContextResponseV1',
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
                                                                                                                            'ProjectContextReadModelV1; '
                                                                                                                            'any '
                                                                                                                            'large '
                                                                                                                            'table '
                                                                                                                            'is '
                                                                                                                            'an '
                                                                                                                            'ArtifactRef'}}}},
                                                   'idempotency': {'mode': 'IDEMPOTENCY_KEY',
                                                                   'scope': 'operation_id + '
                                                                            'project_id + '
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
                                                   'truth_pit_preconditions': ['base_revision_id '
                                                                               'is current',
                                                                               'all referenced '
                                                                               'versioned objects '
                                                                               'exist and are '
                                                                               'compatible'],
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
                                                   'read_models': ['ProjectContextReadModelV1'],
                                                   'frontend_capabilities': ['data '
                                                                             'source/snapshot/universe '
                                                                             'upgrade without '
                                                                             'mutation']},
 'ProjectSessionService.v1.restoreSession': {'operation_id': 'ProjectSessionService.v1.restoreSession',
                                             'version': '1.0.0',
                                             'kind': 'QUERY',
                                             'request_dto': {'name': 'RestoreSessionRequestV1',
                                                             'schema': {'type': 'object',
                                                                        'additionalProperties': False,
                                                                        'required': ['request_id',
                                                                                     'project_id',
                                                                                     'project_context_revision_id',
                                                                                     'expected_api_version',
                                                                                     'session_id'],
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
                                                                                       'session_id': {'type': 'string',
                                                                                                      'description': 'Desktop '
                                                                                                                     'session '
                                                                                                                     'UUID',
                                                                                                      'pattern': '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
                                                                                                      'format': 'uuid'}}}},
                                             'response_dto': {'name': 'RestoreSessionResponseV1',
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
                                                                                                                      'SessionRestoreReadModelV1; '
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
                                             'truth_pit_preconditions': ['ProjectContextRevision '
                                                                         'exists and is not '
                                                                         'superseded for this '
                                                                         'request'],
                                             'errors': ['INVALID_ARGUMENT',
                                                        'VERSION_MISMATCH',
                                                        'NOT_FOUND',
                                                        'SESSION_PROJECT_BINDING_CONFLICT',
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
                                             'read_models': ['SessionRestoreReadModelV1'],
                                             'frontend_capabilities': ['Dockview layout '
                                                                       'restoration',
                                                                       'Lab context restoration']}}

class OpenProjectRequestV1(ClosedDto):
    DTO_NAME = 'OpenProjectRequestV1'
    OPERATION_ID = 'ProjectSessionService.v1.openProject'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.openProject']['request_dto']['schema']

class OpenProjectResponseV1(ClosedDto):
    DTO_NAME = 'OpenProjectResponseV1'
    OPERATION_ID = 'ProjectSessionService.v1.openProject'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.openProject']['response_dto']['schema']

class GetProjectContextRequestV1(ClosedDto):
    DTO_NAME = 'GetProjectContextRequestV1'
    OPERATION_ID = 'ProjectSessionService.v1.getProjectContext'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.getProjectContext']['request_dto']['schema']

class GetProjectContextResponseV1(ClosedDto):
    DTO_NAME = 'GetProjectContextResponseV1'
    OPERATION_ID = 'ProjectSessionService.v1.getProjectContext'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.getProjectContext']['response_dto']['schema']

class ReviseProjectContextRequestV1(ClosedDto):
    DTO_NAME = 'ReviseProjectContextRequestV1'
    OPERATION_ID = 'ProjectSessionService.v1.reviseProjectContext'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.reviseProjectContext']['request_dto']['schema']

class ReviseProjectContextResponseV1(ClosedDto):
    DTO_NAME = 'ReviseProjectContextResponseV1'
    OPERATION_ID = 'ProjectSessionService.v1.reviseProjectContext'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.reviseProjectContext']['response_dto']['schema']

class RestoreSessionRequestV1(ClosedDto):
    DTO_NAME = 'RestoreSessionRequestV1'
    OPERATION_ID = 'ProjectSessionService.v1.restoreSession'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.restoreSession']['request_dto']['schema']

class RestoreSessionResponseV1(ClosedDto):
    DTO_NAME = 'RestoreSessionResponseV1'
    OPERATION_ID = 'ProjectSessionService.v1.restoreSession'
    SCHEMA = METHOD_SPECS['ProjectSessionService.v1.restoreSession']['response_dto']['schema']

OPERATION_IDS = ('ProjectSessionService.v1.openProject',
 'ProjectSessionService.v1.getProjectContext',
 'ProjectSessionService.v1.reviseProjectContext',
 'ProjectSessionService.v1.restoreSession')
OPERATIONS = (
    OperationContract(
        operation_id='ProjectSessionService.v1.openProject',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=OpenProjectRequestV1,
        response_type=OpenProjectResponseV1,
        metadata=METHOD_SPECS['ProjectSessionService.v1.openProject'],
    ),
    OperationContract(
        operation_id='ProjectSessionService.v1.getProjectContext',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetProjectContextRequestV1,
        response_type=GetProjectContextResponseV1,
        metadata=METHOD_SPECS['ProjectSessionService.v1.getProjectContext'],
    ),
    OperationContract(
        operation_id='ProjectSessionService.v1.reviseProjectContext',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=ReviseProjectContextRequestV1,
        response_type=ReviseProjectContextResponseV1,
        metadata=METHOD_SPECS['ProjectSessionService.v1.reviseProjectContext'],
    ),
    OperationContract(
        operation_id='ProjectSessionService.v1.restoreSession',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=RestoreSessionRequestV1,
        response_type=RestoreSessionResponseV1,
        metadata=METHOD_SPECS['ProjectSessionService.v1.restoreSession'],
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
 'OpenProjectRequestV1',
 'OpenProjectResponseV1',
 'GetProjectContextRequestV1',
 'GetProjectContextResponseV1',
 'ReviseProjectContextRequestV1',
 'ReviseProjectContextResponseV1',
 'RestoreSessionRequestV1',
 'RestoreSessionResponseV1')

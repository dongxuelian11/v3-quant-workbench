from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:data_source:1.0.0'
SERVICE = 'DataSourceService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'DataSourceService.v1.listConnectorCapabilities': {'operation_id': 'DataSourceService.v1.listConnectorCapabilities',
                                                    'version': '1.0.0',
                                                    'kind': 'QUERY',
                                                    'request_dto': {'name': 'ListConnectorCapabilitiesRequestV1',
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
                                                    'response_dto': {'name': 'ListConnectorCapabilitiesResponseV1',
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
                                                                                                                             'ConnectorCapabilityListV1; '
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
                                                                                'superseded for '
                                                                                'this request'],
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
                                                    'read_models': ['ConnectorCapabilityListV1'],
                                                    'frontend_capabilities': ['Data Source '
                                                                              'selector',
                                                                              'Formal/Unavailable '
                                                                              'state']},
 'DataSourceService.v1.preflightSwitch': {'operation_id': 'DataSourceService.v1.preflightSwitch',
                                          'version': '1.0.0',
                                          'kind': 'ASYNC_COMMAND',
                                          'request_dto': {'name': 'PreflightSwitchRequestV1',
                                                          'schema': {'type': 'object',
                                                                     'additionalProperties': False,
                                                                     'required': ['request_id',
                                                                                  'project_id',
                                                                                  'project_context_revision_id',
                                                                                  'expected_api_version',
                                                                                  'connector_version_id',
                                                                                  'required_capabilities',
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
                                                                                    'connector_version_id': {'type': 'string',
                                                                                                             'description': 'Immutable '
                                                                                                                            'admitted '
                                                                                                                            'connector '
                                                                                                                            'version'},
                                                                                    'required_capabilities': {'type': 'array',
                                                                                                              'description': 'Capabilities '
                                                                                                                             'required '
                                                                                                                             'by '
                                                                                                                             'current '
                                                                                                                             'ProjectContext',
                                                                                                              'items': {'type': 'string'}},
                                                                                    'idempotency_key': {'type': 'string',
                                                                                                        'description': 'Stable '
                                                                                                                       'switch-preflight '
                                                                                                                       'key'}}}},
                                          'response_dto': {'name': 'PreflightSwitchAcceptedV1',
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
                                                             'run_identity_inputs': ['connector_version_id',
                                                                                     'required_capabilities',
                                                                                     'project_context_revision_id'],
                                                             'artifact_outputs': ['ConnectorPreflightReport'],
                                                             'cancel': 'COOPERATIVE_UNTIL_VALIDATION_COMMIT',
                                                             'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                             'resume': 'FROM_VALIDATED_CHECKPOINT_ONLY',
                                                             'input_change': 'MUST_CREATE_NEW_RUN',
                                                             'attempt_rule': 'retry/resume always '
                                                                             'creates a new '
                                                                             'TaskAttempt; '
                                                                             'previous attempts '
                                                                             'are immutable'},
                                          'truth_pit_preconditions': ['connector version is '
                                                                      'installed and '
                                                                      'quarantined/admitted',
                                                                      'credential reference '
                                                                      'resolves in Windows '
                                                                      'Credential Manager without '
                                                                      'exposing secret'],
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
                                          'frontend_capabilities': ['one-click data-source '
                                                                    'switch']},
 'DataSourceService.v1.commitSwitch': {'operation_id': 'DataSourceService.v1.commitSwitch',
                                       'version': '1.0.0',
                                       'kind': 'COMMAND',
                                       'request_dto': {'name': 'CommitSwitchRequestV1',
                                                       'schema': {'type': 'object',
                                                                  'additionalProperties': False,
                                                                  'required': ['request_id',
                                                                               'project_id',
                                                                               'project_context_revision_id',
                                                                               'expected_api_version',
                                                                               'preflight_artifact_id',
                                                                               'expected_connector_version_id',
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
                                                                                 'preflight_artifact_id': {'type': 'string',
                                                                                                           'description': 'Content-addressed '
                                                                                                                          'artifact '
                                                                                                                          'identity',
                                                                                                           'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                 'expected_connector_version_id': {'type': 'string',
                                                                                                                   'description': 'Version '
                                                                                                                                  'proven '
                                                                                                                                  'by '
                                                                                                                                  'preflight'},
                                                                                 'idempotency_key': {'type': 'string',
                                                                                                     'description': 'Stable '
                                                                                                                    'commit '
                                                                                                                    'key'}}}},
                                       'response_dto': {'name': 'CommitSwitchResponseV1',
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
                                                                                                                'ConnectorSwitchReadModelV1; '
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
                                       'truth_pit_preconditions': ['preflight artifact is '
                                                                   'FORMAL-valid and matches '
                                                                   'current ProjectContext '
                                                                   'revision',
                                                                   'switch is atomic and creates a '
                                                                   'new ProjectContext revision'],
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
                                       'read_models': ['ConnectorSwitchReadModelV1'],
                                       'frontend_capabilities': ['one-click data-source switch']},
 'DataSourceService.v1.admitConnectorVersion': {'operation_id': 'DataSourceService.v1.admitConnectorVersion',
                                                'version': '1.0.0',
                                                'kind': 'ASYNC_COMMAND',
                                                'request_dto': {'name': 'AdmitConnectorVersionRequestV1',
                                                                'schema': {'type': 'object',
                                                                           'additionalProperties': False,
                                                                           'required': ['request_id',
                                                                                        'project_id',
                                                                                        'project_context_revision_id',
                                                                                        'expected_api_version',
                                                                                        'connector_bundle_artifact_id',
                                                                                        'admission_profile_id',
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
                                                                                          'connector_bundle_artifact_id': {'type': 'string',
                                                                                                                           'description': 'Content-addressed '
                                                                                                                                          'artifact '
                                                                                                                                          'identity',
                                                                                                                           'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                          'admission_profile_id': {'type': 'string',
                                                                                                                   'description': 'Pinned '
                                                                                                                                  'admission '
                                                                                                                                  'policy '
                                                                                                                                  'version'},
                                                                                          'idempotency_key': {'type': 'string',
                                                                                                              'description': 'Stable '
                                                                                                                             'admission '
                                                                                                                             'key'}}}},
                                                'response_dto': {'name': 'AdmitConnectorVersionAcceptedV1',
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
                                                                'scope': 'operation_id + '
                                                                         'project_id + '
                                                                         'idempotency_key/request_id',
                                                                'same_key_same_canonical_request': 'return_original_outcome',
                                                                'same_key_different_canonical_request': 'IDEMPOTENCY_CONFLICT'},
                                                'async_behavior': {'creates_task_run': True,
                                                                   'run_identity_inputs': ['bundle '
                                                                                           'content '
                                                                                           'hash',
                                                                                           'admission_profile_id',
                                                                                           'environment_profile_id'],
                                                                   'artifact_outputs': ['ConnectorAdmissionReport',
                                                                                        'ConnectorCapabilityMatrix'],
                                                                   'cancel': 'COOPERATIVE',
                                                                   'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                                   'resume': 'NOT_SUPPORTED',
                                                                   'input_change': 'MUST_CREATE_NEW_RUN',
                                                                   'attempt_rule': 'retry/resume '
                                                                                   'always creates '
                                                                                   'a new '
                                                                                   'TaskAttempt; '
                                                                                   'previous '
                                                                                   'attempts are '
                                                                                   'immutable'},
                                                'truth_pit_preconditions': ['bundle remains '
                                                                            'quarantined until '
                                                                            'every declared '
                                                                            'capability passes',
                                                                            'network behavior is '
                                                                            'deny-by-default and '
                                                                            'declared'],
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
                                                'frontend_capabilities': ['connector plugin '
                                                                          'admission']}}

class ListConnectorCapabilitiesRequestV1(ClosedDto):
    DTO_NAME = 'ListConnectorCapabilitiesRequestV1'
    OPERATION_ID = 'DataSourceService.v1.listConnectorCapabilities'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.listConnectorCapabilities']['request_dto']['schema']

class ListConnectorCapabilitiesResponseV1(ClosedDto):
    DTO_NAME = 'ListConnectorCapabilitiesResponseV1'
    OPERATION_ID = 'DataSourceService.v1.listConnectorCapabilities'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.listConnectorCapabilities']['response_dto']['schema']

class PreflightSwitchRequestV1(ClosedDto):
    DTO_NAME = 'PreflightSwitchRequestV1'
    OPERATION_ID = 'DataSourceService.v1.preflightSwitch'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.preflightSwitch']['request_dto']['schema']

class PreflightSwitchAcceptedV1(ClosedDto):
    DTO_NAME = 'PreflightSwitchAcceptedV1'
    OPERATION_ID = 'DataSourceService.v1.preflightSwitch'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.preflightSwitch']['response_dto']['schema']

class CommitSwitchRequestV1(ClosedDto):
    DTO_NAME = 'CommitSwitchRequestV1'
    OPERATION_ID = 'DataSourceService.v1.commitSwitch'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.commitSwitch']['request_dto']['schema']

class CommitSwitchResponseV1(ClosedDto):
    DTO_NAME = 'CommitSwitchResponseV1'
    OPERATION_ID = 'DataSourceService.v1.commitSwitch'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.commitSwitch']['response_dto']['schema']

class AdmitConnectorVersionRequestV1(ClosedDto):
    DTO_NAME = 'AdmitConnectorVersionRequestV1'
    OPERATION_ID = 'DataSourceService.v1.admitConnectorVersion'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.admitConnectorVersion']['request_dto']['schema']

class AdmitConnectorVersionAcceptedV1(ClosedDto):
    DTO_NAME = 'AdmitConnectorVersionAcceptedV1'
    OPERATION_ID = 'DataSourceService.v1.admitConnectorVersion'
    SCHEMA = METHOD_SPECS['DataSourceService.v1.admitConnectorVersion']['response_dto']['schema']

OPERATION_IDS = ('DataSourceService.v1.listConnectorCapabilities',
 'DataSourceService.v1.preflightSwitch',
 'DataSourceService.v1.commitSwitch',
 'DataSourceService.v1.admitConnectorVersion')
OPERATIONS = (
    OperationContract(
        operation_id='DataSourceService.v1.listConnectorCapabilities',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ListConnectorCapabilitiesRequestV1,
        response_type=ListConnectorCapabilitiesResponseV1,
        metadata=METHOD_SPECS['DataSourceService.v1.listConnectorCapabilities'],
    ),
    OperationContract(
        operation_id='DataSourceService.v1.preflightSwitch',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=PreflightSwitchRequestV1,
        response_type=PreflightSwitchAcceptedV1,
        metadata=METHOD_SPECS['DataSourceService.v1.preflightSwitch'],
    ),
    OperationContract(
        operation_id='DataSourceService.v1.commitSwitch',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=CommitSwitchRequestV1,
        response_type=CommitSwitchResponseV1,
        metadata=METHOD_SPECS['DataSourceService.v1.commitSwitch'],
    ),
    OperationContract(
        operation_id='DataSourceService.v1.admitConnectorVersion',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=AdmitConnectorVersionRequestV1,
        response_type=AdmitConnectorVersionAcceptedV1,
        metadata=METHOD_SPECS['DataSourceService.v1.admitConnectorVersion'],
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
 'ListConnectorCapabilitiesRequestV1',
 'ListConnectorCapabilitiesResponseV1',
 'PreflightSwitchRequestV1',
 'PreflightSwitchAcceptedV1',
 'CommitSwitchRequestV1',
 'CommitSwitchResponseV1',
 'AdmitConnectorVersionRequestV1',
 'AdmitConnectorVersionAcceptedV1')

from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:universe:1.0.0'
SERVICE = 'UniverseService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'UniverseService.v1.validateUniverseDefinition': {'operation_id': 'UniverseService.v1.validateUniverseDefinition',
                                                   'version': '1.0.0',
                                                   'kind': 'QUERY',
                                                   'request_dto': {'name': 'ValidateUniverseDefinitionRequestV1',
                                                                   'schema': {'type': 'object',
                                                                              'additionalProperties': False,
                                                                              'required': ['request_id',
                                                                                           'project_id',
                                                                                           'project_context_revision_id',
                                                                                           'expected_api_version',
                                                                                           'constructor_kind',
                                                                                           'definition'],
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
                                                                                             'constructor_kind': {'type': 'string',
                                                                                                                  'description': 'One '
                                                                                                                                 'of '
                                                                                                                                 'nine '
                                                                                                                                 'accepted '
                                                                                                                                 'constructor '
                                                                                                                                 'kinds'},
                                                                                             'definition': {'type': 'object',
                                                                                                            'description': 'Constructor-specific '
                                                                                                                           'typed '
                                                                                                                           'definition'}}}},
                                                   'response_dto': {'name': 'ValidateUniverseDefinitionResponseV1',
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
                                                                                                                            'UniverseValidationReadModelV1; '
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
                                                   'read_models': ['UniverseValidationReadModelV1'],
                                                   'frontend_capabilities': ['nine Universe '
                                                                             'constructors',
                                                                             'CSV/TSV unresolved '
                                                                             'preview']},
 'UniverseService.v1.publishUniverseDefinition': {'operation_id': 'UniverseService.v1.publishUniverseDefinition',
                                                  'version': '1.0.0',
                                                  'kind': 'COMMAND',
                                                  'request_dto': {'name': 'PublishUniverseDefinitionRequestV1',
                                                                  'schema': {'type': 'object',
                                                                             'additionalProperties': False,
                                                                             'required': ['request_id',
                                                                                          'project_id',
                                                                                          'project_context_revision_id',
                                                                                          'expected_api_version',
                                                                                          'constructor_kind',
                                                                                          'definition',
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
                                                                                            'constructor_kind': {'type': 'string',
                                                                                                                 'description': 'Accepted '
                                                                                                                                'constructor '
                                                                                                                                'kind'},
                                                                                            'definition': {'type': 'object',
                                                                                                           'description': 'Validated '
                                                                                                                          'definition'},
                                                                                            'idempotency_key': {'type': 'string',
                                                                                                                'description': 'Stable '
                                                                                                                               'publication '
                                                                                                                               'key'}}}},
                                                  'response_dto': {'name': 'PublishUniverseDefinitionResponseV1',
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
                                                                                                                           'UniverseDefinitionReadModelV1; '
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
                                                  'truth_pit_preconditions': ['every explicitly '
                                                                              'named instrument '
                                                                              'resolves or remains '
                                                                              'visibly unresolved; '
                                                                              'no silent dropping'],
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
                                                  'read_models': ['UniverseDefinitionReadModelV1'],
                                                  'frontend_capabilities': []},
 'UniverseService.v1.resolveUniverseVersion': {'operation_id': 'UniverseService.v1.resolveUniverseVersion',
                                               'version': '1.0.0',
                                               'kind': 'ASYNC_COMMAND',
                                               'request_dto': {'name': 'ResolveUniverseVersionRequestV1',
                                                               'schema': {'type': 'object',
                                                                          'additionalProperties': False,
                                                                          'required': ['request_id',
                                                                                       'project_id',
                                                                                       'project_context_revision_id',
                                                                                       'expected_api_version',
                                                                                       'universe_definition_id',
                                                                                       'snapshot_id',
                                                                                       'knowledge_cutoff',
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
                                                                                         'universe_definition_id': {'type': 'string',
                                                                                                                    'description': 'Immutable '
                                                                                                                                   'definition '
                                                                                                                                   'identity'},
                                                                                         'snapshot_id': {'type': 'string',
                                                                                                         'description': 'Published '
                                                                                                                        'immutable '
                                                                                                                        'data '
                                                                                                                        'snapshot '
                                                                                                                        'identity',
                                                                                                         'pattern': '^snp_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                         'knowledge_cutoff': {'type': 'string',
                                                                                                              'description': 'PIT '
                                                                                                                             'availability '
                                                                                                                             'cutoff',
                                                                                                              'format': 'date-time'},
                                                                                         'idempotency_key': {'type': 'string',
                                                                                                             'description': 'Stable '
                                                                                                                            'resolution '
                                                                                                                            'key'}}}},
                                               'response_dto': {'name': 'ResolveUniverseVersionAcceptedV1',
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
                                                               'scope': 'operation_id + project_id '
                                                                        '+ '
                                                                        'idempotency_key/request_id',
                                                               'same_key_same_canonical_request': 'return_original_outcome',
                                                               'same_key_different_canonical_request': 'IDEMPOTENCY_CONFLICT'},
                                               'async_behavior': {'creates_task_run': True,
                                                                  'run_identity_inputs': ['definition '
                                                                                          'hash',
                                                                                          'snapshot_id',
                                                                                          'knowledge_cutoff',
                                                                                          'taxonomy '
                                                                                          'version'],
                                                                  'artifact_outputs': ['UniverseMembershipParquet',
                                                                                       'UniverseAuditReport'],
                                                                  'cancel': 'COOPERATIVE',
                                                                  'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                                  'resume': 'FROM_PARTITION_CHECKPOINT',
                                                                  'input_change': 'MUST_CREATE_NEW_RUN',
                                                                  'attempt_rule': 'retry/resume '
                                                                                  'always creates '
                                                                                  'a new '
                                                                                  'TaskAttempt; '
                                                                                  'previous '
                                                                                  'attempts are '
                                                                                  'immutable'},
                                               'truth_pit_preconditions': ['snapshot is PUBLISHED '
                                                                           'and pinned',
                                                                           'historical membership '
                                                                           'is evaluated as known '
                                                                           'at cutoff',
                                                                           'present-day membership '
                                                                           'backfill forbidden'],
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
                                               'frontend_capabilities': ['Universe grid',
                                                                         'historical Universe']}}

class ValidateUniverseDefinitionRequestV1(ClosedDto):
    DTO_NAME = 'ValidateUniverseDefinitionRequestV1'
    OPERATION_ID = 'UniverseService.v1.validateUniverseDefinition'
    SCHEMA = METHOD_SPECS['UniverseService.v1.validateUniverseDefinition']['request_dto']['schema']

class ValidateUniverseDefinitionResponseV1(ClosedDto):
    DTO_NAME = 'ValidateUniverseDefinitionResponseV1'
    OPERATION_ID = 'UniverseService.v1.validateUniverseDefinition'
    SCHEMA = METHOD_SPECS['UniverseService.v1.validateUniverseDefinition']['response_dto']['schema']

class PublishUniverseDefinitionRequestV1(ClosedDto):
    DTO_NAME = 'PublishUniverseDefinitionRequestV1'
    OPERATION_ID = 'UniverseService.v1.publishUniverseDefinition'
    SCHEMA = METHOD_SPECS['UniverseService.v1.publishUniverseDefinition']['request_dto']['schema']

class PublishUniverseDefinitionResponseV1(ClosedDto):
    DTO_NAME = 'PublishUniverseDefinitionResponseV1'
    OPERATION_ID = 'UniverseService.v1.publishUniverseDefinition'
    SCHEMA = METHOD_SPECS['UniverseService.v1.publishUniverseDefinition']['response_dto']['schema']

class ResolveUniverseVersionRequestV1(ClosedDto):
    DTO_NAME = 'ResolveUniverseVersionRequestV1'
    OPERATION_ID = 'UniverseService.v1.resolveUniverseVersion'
    SCHEMA = METHOD_SPECS['UniverseService.v1.resolveUniverseVersion']['request_dto']['schema']

class ResolveUniverseVersionAcceptedV1(ClosedDto):
    DTO_NAME = 'ResolveUniverseVersionAcceptedV1'
    OPERATION_ID = 'UniverseService.v1.resolveUniverseVersion'
    SCHEMA = METHOD_SPECS['UniverseService.v1.resolveUniverseVersion']['response_dto']['schema']

OPERATION_IDS = ('UniverseService.v1.validateUniverseDefinition',
 'UniverseService.v1.publishUniverseDefinition',
 'UniverseService.v1.resolveUniverseVersion')
OPERATIONS = (
    OperationContract(
        operation_id='UniverseService.v1.validateUniverseDefinition',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ValidateUniverseDefinitionRequestV1,
        response_type=ValidateUniverseDefinitionResponseV1,
        metadata=METHOD_SPECS['UniverseService.v1.validateUniverseDefinition'],
    ),
    OperationContract(
        operation_id='UniverseService.v1.publishUniverseDefinition',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=PublishUniverseDefinitionRequestV1,
        response_type=PublishUniverseDefinitionResponseV1,
        metadata=METHOD_SPECS['UniverseService.v1.publishUniverseDefinition'],
    ),
    OperationContract(
        operation_id='UniverseService.v1.resolveUniverseVersion',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=ResolveUniverseVersionRequestV1,
        response_type=ResolveUniverseVersionAcceptedV1,
        metadata=METHOD_SPECS['UniverseService.v1.resolveUniverseVersion'],
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
 'ValidateUniverseDefinitionRequestV1',
 'ValidateUniverseDefinitionResponseV1',
 'PublishUniverseDefinitionRequestV1',
 'PublishUniverseDefinitionResponseV1',
 'ResolveUniverseVersionRequestV1',
 'ResolveUniverseVersionAcceptedV1')

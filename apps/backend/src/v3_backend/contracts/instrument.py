from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:instrument:1.0.0'
SERVICE = 'InstrumentService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'InstrumentService.v1.getInstrument': {'operation_id': 'InstrumentService.v1.getInstrument',
                                        'version': '1.0.0',
                                        'kind': 'QUERY',
                                        'request_dto': {'name': 'GetInstrumentRequestV1',
                                                        'schema': {'type': 'object',
                                                                   'additionalProperties': False,
                                                                   'required': ['request_id',
                                                                                'project_id',
                                                                                'project_context_revision_id',
                                                                                'expected_api_version',
                                                                                'instrument_id'],
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
                                                                                  'instrument_id': {'type': 'string',
                                                                                                    'description': 'Permanent '
                                                                                                                   'V3 '
                                                                                                                   'InstrumentId'}}}},
                                        'response_dto': {'name': 'GetInstrumentResponseV1',
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
                                                                                                                 'InstrumentReadModelV1; '
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
                                                                    'and is not superseded for '
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
                                        'read_models': ['InstrumentReadModelV1'],
                                        'frontend_capabilities': ['Universe grid', 'Inspector']},
 'InstrumentService.v1.resolveProviderAlias': {'operation_id': 'InstrumentService.v1.resolveProviderAlias',
                                               'version': '1.0.0',
                                               'kind': 'QUERY',
                                               'request_dto': {'name': 'ResolveProviderAliasRequestV1',
                                                               'schema': {'type': 'object',
                                                                          'additionalProperties': False,
                                                                          'required': ['request_id',
                                                                                       'project_id',
                                                                                       'project_context_revision_id',
                                                                                       'expected_api_version',
                                                                                       'connector_version_id',
                                                                                       'provider_code',
                                                                                       'as_of'],
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
                                                                                                                  'description': 'Provider '
                                                                                                                                 'namespace '
                                                                                                                                 'owner'},
                                                                                         'provider_code': {'type': 'string',
                                                                                                           'description': 'Provider '
                                                                                                                          'symbol'},
                                                                                         'as_of': {'type': 'string',
                                                                                                   'description': 'Effective '
                                                                                                                  'timestamp',
                                                                                                   'format': 'date-time'}}}},
                                               'response_dto': {'name': 'ResolveProviderAliasResponseV1',
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
                                                                                                                        'InstrumentAliasResolutionV1; '
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
                                               'truth_pit_preconditions': ['alias effective '
                                                                           'interval contains '
                                                                           'as_of',
                                                                           'exactly one '
                                                                           'InstrumentId resolves; '
                                                                           'conflict fails closed'],
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
                                               'read_models': ['InstrumentAliasResolutionV1'],
                                               'frontend_capabilities': ['CSV/TSV unresolved '
                                                                         'preview']},
 'InstrumentService.v1.publishInstrumentRevision': {'operation_id': 'InstrumentService.v1.publishInstrumentRevision',
                                                    'version': '1.0.0',
                                                    'kind': 'COMMAND',
                                                    'request_dto': {'name': 'PublishInstrumentRevisionRequestV1',
                                                                    'schema': {'type': 'object',
                                                                               'additionalProperties': False,
                                                                               'required': ['request_id',
                                                                                            'project_id',
                                                                                            'project_context_revision_id',
                                                                                            'expected_api_version',
                                                                                            'instrument_id',
                                                                                            'base_revision',
                                                                                            'changes',
                                                                                            'evidence_artifact_id',
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
                                                                                              'instrument_id': {'type': 'string',
                                                                                                                'description': 'Permanent '
                                                                                                                               'identity'},
                                                                                              'base_revision': {'type': 'integer',
                                                                                                                'description': 'Optimistic-lock '
                                                                                                                               'revision',
                                                                                                                'minimum': 0},
                                                                                              'changes': {'type': 'object',
                                                                                                          'description': 'Allow-listed '
                                                                                                                         'lifecycle '
                                                                                                                         'metadata '
                                                                                                                         'only'},
                                                                                              'evidence_artifact_id': {'type': 'string',
                                                                                                                       'description': 'Content-addressed '
                                                                                                                                      'artifact '
                                                                                                                                      'identity',
                                                                                                                       'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                              'idempotency_key': {'type': 'string',
                                                                                                                  'description': 'Stable '
                                                                                                                                 'publication '
                                                                                                                                 'key'}}}},
                                                    'response_dto': {'name': 'PublishInstrumentRevisionResponseV1',
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
                                                                                                                             'InstrumentReadModelV1; '
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
                                                    'truth_pit_preconditions': ['evidence artifact '
                                                                                'published',
                                                                                'provider aliases '
                                                                                'have '
                                                                                'non-overlapping '
                                                                                'effective '
                                                                                'intervals'],
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
                                                    'read_models': ['InstrumentReadModelV1'],
                                                    'frontend_capabilities': []}}

class GetInstrumentRequestV1(ClosedDto):
    DTO_NAME = 'GetInstrumentRequestV1'
    OPERATION_ID = 'InstrumentService.v1.getInstrument'
    SCHEMA = METHOD_SPECS['InstrumentService.v1.getInstrument']['request_dto']['schema']

class GetInstrumentResponseV1(ClosedDto):
    DTO_NAME = 'GetInstrumentResponseV1'
    OPERATION_ID = 'InstrumentService.v1.getInstrument'
    SCHEMA = METHOD_SPECS['InstrumentService.v1.getInstrument']['response_dto']['schema']

class ResolveProviderAliasRequestV1(ClosedDto):
    DTO_NAME = 'ResolveProviderAliasRequestV1'
    OPERATION_ID = 'InstrumentService.v1.resolveProviderAlias'
    SCHEMA = METHOD_SPECS['InstrumentService.v1.resolveProviderAlias']['request_dto']['schema']

class ResolveProviderAliasResponseV1(ClosedDto):
    DTO_NAME = 'ResolveProviderAliasResponseV1'
    OPERATION_ID = 'InstrumentService.v1.resolveProviderAlias'
    SCHEMA = METHOD_SPECS['InstrumentService.v1.resolveProviderAlias']['response_dto']['schema']

class PublishInstrumentRevisionRequestV1(ClosedDto):
    DTO_NAME = 'PublishInstrumentRevisionRequestV1'
    OPERATION_ID = 'InstrumentService.v1.publishInstrumentRevision'
    SCHEMA = METHOD_SPECS['InstrumentService.v1.publishInstrumentRevision']['request_dto']['schema']

class PublishInstrumentRevisionResponseV1(ClosedDto):
    DTO_NAME = 'PublishInstrumentRevisionResponseV1'
    OPERATION_ID = 'InstrumentService.v1.publishInstrumentRevision'
    SCHEMA = METHOD_SPECS['InstrumentService.v1.publishInstrumentRevision']['response_dto']['schema']

OPERATION_IDS = ('InstrumentService.v1.getInstrument',
 'InstrumentService.v1.resolveProviderAlias',
 'InstrumentService.v1.publishInstrumentRevision')
OPERATIONS = (
    OperationContract(
        operation_id='InstrumentService.v1.getInstrument',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetInstrumentRequestV1,
        response_type=GetInstrumentResponseV1,
        metadata=METHOD_SPECS['InstrumentService.v1.getInstrument'],
    ),
    OperationContract(
        operation_id='InstrumentService.v1.resolveProviderAlias',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ResolveProviderAliasRequestV1,
        response_type=ResolveProviderAliasResponseV1,
        metadata=METHOD_SPECS['InstrumentService.v1.resolveProviderAlias'],
    ),
    OperationContract(
        operation_id='InstrumentService.v1.publishInstrumentRevision',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=PublishInstrumentRevisionRequestV1,
        response_type=PublishInstrumentRevisionResponseV1,
        metadata=METHOD_SPECS['InstrumentService.v1.publishInstrumentRevision'],
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
 'GetInstrumentRequestV1',
 'GetInstrumentResponseV1',
 'ResolveProviderAliasRequestV1',
 'ResolveProviderAliasResponseV1',
 'PublishInstrumentRevisionRequestV1',
 'PublishInstrumentRevisionResponseV1')

from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:strategy:1.0.0'
SERVICE = 'StrategyService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'StrategyService.v1.validateStrategyDraft': {'operation_id': 'StrategyService.v1.validateStrategyDraft',
                                              'version': '1.0.0',
                                              'kind': 'QUERY',
                                              'request_dto': {'name': 'ValidateStrategyDraftRequestV1',
                                                              'schema': {'type': 'object',
                                                                         'additionalProperties': False,
                                                                         'required': ['request_id',
                                                                                      'project_id',
                                                                                      'project_context_revision_id',
                                                                                      'expected_api_version',
                                                                                      'draft',
                                                                                      'mode'],
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
                                                                                        'draft': {'type': 'object',
                                                                                                  'description': 'Visual '
                                                                                                                 'graph '
                                                                                                                 '+ '
                                                                                                                 'code '
                                                                                                                 '+ '
                                                                                                                 'deterministic '
                                                                                                                 'synchronization '
                                                                                                                 'metadata'},
                                                                                        'mode': {'type': 'string',
                                                                                                 'description': 'Visual, '
                                                                                                                'Code '
                                                                                                                'or '
                                                                                                                'Split',
                                                                                                 'enum': ['VISUAL',
                                                                                                          'CODE',
                                                                                                          'SPLIT']}}}},
                                              'response_dto': {'name': 'ValidateStrategyDraftResponseV1',
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
                                                                                                                       'StrategyValidationReadModelV1; '
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
                                              'read_models': ['StrategyValidationReadModelV1'],
                                              'frontend_capabilities': ['Visual/Code/Split',
                                                                        'validation',
                                                                        'graph selection '
                                                                        'Inspector']},
 'StrategyService.v1.compileStrategyIr': {'operation_id': 'StrategyService.v1.compileStrategyIr',
                                          'version': '1.0.0',
                                          'kind': 'ASYNC_COMMAND',
                                          'request_dto': {'name': 'CompileStrategyIrRequestV1',
                                                          'schema': {'type': 'object',
                                                                     'additionalProperties': False,
                                                                     'required': ['request_id',
                                                                                  'project_id',
                                                                                  'project_context_revision_id',
                                                                                  'expected_api_version',
                                                                                  'draft_content_hash',
                                                                                  'draft_artifact_id',
                                                                                  'compiler_profile_id',
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
                                                                                    'draft_content_hash': {'type': 'string',
                                                                                                           'description': 'Exact '
                                                                                                                          'validated '
                                                                                                                          'draft '
                                                                                                                          'hash',
                                                                                                           'pattern': '^[0-9a-f]{64}$'},
                                                                                    'draft_artifact_id': {'type': 'string',
                                                                                                          'description': 'Content-addressed '
                                                                                                                         'artifact '
                                                                                                                         'identity',
                                                                                                          'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                    'compiler_profile_id': {'type': 'string',
                                                                                                            'description': 'Pinned '
                                                                                                                           'Strategy '
                                                                                                                           'IR '
                                                                                                                           'compiler'},
                                                                                    'idempotency_key': {'type': 'string',
                                                                                                        'description': 'Stable '
                                                                                                                       'compile '
                                                                                                                       'key'}}}},
                                          'response_dto': {'name': 'CompileStrategyIrAcceptedV1',
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
                                                             'run_identity_inputs': ['draft hash',
                                                                                     'compiler '
                                                                                     'profile',
                                                                                     'code '
                                                                                     'version'],
                                                             'artifact_outputs': ['StrategyIR',
                                                                                  'ValidationDiagnostics'],
                                                             'cancel': 'COOPERATIVE',
                                                             'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                             'resume': 'NOT_SUPPORTED',
                                                             'input_change': 'MUST_CREATE_NEW_RUN',
                                                             'attempt_rule': 'retry/resume always '
                                                                             'creates a new '
                                                                             'TaskAttempt; '
                                                                             'previous attempts '
                                                                             'are immutable'},
                                          'truth_pit_preconditions': ['strategy uses V3 API only',
                                                                      'no direct DB, network, '
                                                                      'RQAlpha or future-data '
                                                                      'access'],
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
                                          'frontend_capabilities': ['deterministic patch seam',
                                                                    'validation/handoff']},
 'StrategyService.v1.publishStrategyVersion': {'operation_id': 'StrategyService.v1.publishStrategyVersion',
                                               'version': '1.0.0',
                                               'kind': 'COMMAND',
                                               'request_dto': {'name': 'PublishStrategyVersionRequestV1',
                                                               'schema': {'type': 'object',
                                                                          'additionalProperties': False,
                                                                          'required': ['request_id',
                                                                                       'project_id',
                                                                                       'project_context_revision_id',
                                                                                       'expected_api_version',
                                                                                       'strategy_ir_artifact_id',
                                                                                       'validation_artifact_id',
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
                                                                                         'strategy_ir_artifact_id': {'type': 'string',
                                                                                                                     'description': 'Content-addressed '
                                                                                                                                    'artifact '
                                                                                                                                    'identity',
                                                                                                                     'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                         'validation_artifact_id': {'type': 'string',
                                                                                                                    'description': 'Content-addressed '
                                                                                                                                   'artifact '
                                                                                                                                   'identity',
                                                                                                                    'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                         'idempotency_key': {'type': 'string',
                                                                                                             'description': 'Stable '
                                                                                                                            'publish '
                                                                                                                            'key'}}}},
                                               'response_dto': {'name': 'PublishStrategyVersionResponseV1',
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
                                                                                                                        'StrategyVersionReadModelV1; '
                                                                                                                        'any '
                                                                                                                        'large '
                                                                                                                        'table '
                                                                                                                        'is '
                                                                                                                        'an '
                                                                                                                        'ArtifactRef'}}}},
                                               'idempotency': {'mode': 'IDEMPOTENCY_KEY',
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
                                               'truth_pit_preconditions': ['compiler and '
                                                                           'validation artifacts '
                                                                           'match',
                                                                           'published '
                                                                           'StrategyVersion '
                                                                           'immutable'],
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
                                               'read_models': ['StrategyVersionReadModelV1'],
                                               'frontend_capabilities': ['BacktestHandoffDraft']}}

class ValidateStrategyDraftRequestV1(ClosedDto):
    DTO_NAME = 'ValidateStrategyDraftRequestV1'
    OPERATION_ID = 'StrategyService.v1.validateStrategyDraft'
    SCHEMA = METHOD_SPECS['StrategyService.v1.validateStrategyDraft']['request_dto']['schema']

class ValidateStrategyDraftResponseV1(ClosedDto):
    DTO_NAME = 'ValidateStrategyDraftResponseV1'
    OPERATION_ID = 'StrategyService.v1.validateStrategyDraft'
    SCHEMA = METHOD_SPECS['StrategyService.v1.validateStrategyDraft']['response_dto']['schema']

class CompileStrategyIrRequestV1(ClosedDto):
    DTO_NAME = 'CompileStrategyIrRequestV1'
    OPERATION_ID = 'StrategyService.v1.compileStrategyIr'
    SCHEMA = METHOD_SPECS['StrategyService.v1.compileStrategyIr']['request_dto']['schema']

class CompileStrategyIrAcceptedV1(ClosedDto):
    DTO_NAME = 'CompileStrategyIrAcceptedV1'
    OPERATION_ID = 'StrategyService.v1.compileStrategyIr'
    SCHEMA = METHOD_SPECS['StrategyService.v1.compileStrategyIr']['response_dto']['schema']

class PublishStrategyVersionRequestV1(ClosedDto):
    DTO_NAME = 'PublishStrategyVersionRequestV1'
    OPERATION_ID = 'StrategyService.v1.publishStrategyVersion'
    SCHEMA = METHOD_SPECS['StrategyService.v1.publishStrategyVersion']['request_dto']['schema']

class PublishStrategyVersionResponseV1(ClosedDto):
    DTO_NAME = 'PublishStrategyVersionResponseV1'
    OPERATION_ID = 'StrategyService.v1.publishStrategyVersion'
    SCHEMA = METHOD_SPECS['StrategyService.v1.publishStrategyVersion']['response_dto']['schema']

OPERATION_IDS = ('StrategyService.v1.validateStrategyDraft',
 'StrategyService.v1.compileStrategyIr',
 'StrategyService.v1.publishStrategyVersion')
OPERATIONS = (
    OperationContract(
        operation_id='StrategyService.v1.validateStrategyDraft',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ValidateStrategyDraftRequestV1,
        response_type=ValidateStrategyDraftResponseV1,
        metadata=METHOD_SPECS['StrategyService.v1.validateStrategyDraft'],
    ),
    OperationContract(
        operation_id='StrategyService.v1.compileStrategyIr',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=CompileStrategyIrRequestV1,
        response_type=CompileStrategyIrAcceptedV1,
        metadata=METHOD_SPECS['StrategyService.v1.compileStrategyIr'],
    ),
    OperationContract(
        operation_id='StrategyService.v1.publishStrategyVersion',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=PublishStrategyVersionRequestV1,
        response_type=PublishStrategyVersionResponseV1,
        metadata=METHOD_SPECS['StrategyService.v1.publishStrategyVersion'],
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
 'ValidateStrategyDraftRequestV1',
 'ValidateStrategyDraftResponseV1',
 'CompileStrategyIrRequestV1',
 'CompileStrategyIrAcceptedV1',
 'PublishStrategyVersionRequestV1',
 'PublishStrategyVersionResponseV1')

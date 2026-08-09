from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:portfolio:1.0.0'
SERVICE = 'PortfolioService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'PortfolioService.v1.validateConstructionSpec': {'operation_id': 'PortfolioService.v1.validateConstructionSpec',
                                                  'version': '1.0.0',
                                                  'kind': 'QUERY',
                                                  'request_dto': {'name': 'ValidateConstructionSpecRequestV1',
                                                                  'schema': {'type': 'object',
                                                                             'additionalProperties': False,
                                                                             'required': ['request_id',
                                                                                          'project_id',
                                                                                          'project_context_revision_id',
                                                                                          'expected_api_version',
                                                                                          'construction_spec'],
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
                                                                                            'construction_spec': {'type': 'object',
                                                                                                                  'description': 'Selection, '
                                                                                                                                 'weighting, '
                                                                                                                                 'rebalance '
                                                                                                                                 'and '
                                                                                                                                 'turnover '
                                                                                                                                 'rules'}}}},
                                                  'response_dto': {'name': 'ValidateConstructionSpecResponseV1',
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
                                                                                                                           'PortfolioSpecValidationV1; '
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
                                                  'read_models': ['PortfolioSpecValidationV1'],
                                                  'frontend_capabilities': ['Portfolio settings']},
 'PortfolioService.v1.materializePortfolioTargets': {'operation_id': 'PortfolioService.v1.materializePortfolioTargets',
                                                     'version': '1.0.0',
                                                     'kind': 'ASYNC_COMMAND',
                                                     'request_dto': {'name': 'MaterializePortfolioTargetsRequestV1',
                                                                     'schema': {'type': 'object',
                                                                                'additionalProperties': False,
                                                                                'required': ['request_id',
                                                                                             'project_id',
                                                                                             'project_context_revision_id',
                                                                                             'expected_api_version',
                                                                                             'portfolio_spec_id',
                                                                                             'signal_version_id',
                                                                                             'universe_version_id',
                                                                                             'as_of_schedule_artifact_id',
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
                                                                                               'portfolio_spec_id': {'type': 'string',
                                                                                                                     'description': 'Immutable '
                                                                                                                                    'construction '
                                                                                                                                    'spec'},
                                                                                               'signal_version_id': {'type': 'string',
                                                                                                                     'description': 'Pinned '
                                                                                                                                    'prediction '
                                                                                                                                    'signal'},
                                                                                               'universe_version_id': {'type': 'string',
                                                                                                                       'description': 'Pinned '
                                                                                                                                      'universe'},
                                                                                               'as_of_schedule_artifact_id': {'type': 'string',
                                                                                                                              'description': 'Content-addressed '
                                                                                                                                             'artifact '
                                                                                                                                             'identity',
                                                                                                                              'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                                               'idempotency_key': {'type': 'string',
                                                                                                                   'description': 'Stable '
                                                                                                                                  'target '
                                                                                                                                  'key'}}}},
                                                     'response_dto': {'name': 'MaterializePortfolioTargetsAcceptedV1',
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
                                                                        'run_identity_inputs': ['portfolio '
                                                                                                'spec',
                                                                                                'signal '
                                                                                                'hash',
                                                                                                'universe',
                                                                                                'schedule'],
                                                                        'artifact_outputs': ['PortfolioTargetsParquet',
                                                                                             'ConstructionDiagnostics'],
                                                                        'cancel': 'COOPERATIVE',
                                                                        'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                                        'resume': 'FROM_REBALANCE_CHECKPOINT',
                                                                        'input_change': 'MUST_CREATE_NEW_RUN',
                                                                        'attempt_rule': 'retry/resume '
                                                                                        'always '
                                                                                        'creates a '
                                                                                        'new '
                                                                                        'TaskAttempt; '
                                                                                        'previous '
                                                                                        'attempts '
                                                                                        'are '
                                                                                        'immutable'},
                                                     'truth_pit_preconditions': ['signals and '
                                                                                 'universe share '
                                                                                 'PIT-compatible '
                                                                                 'snapshot',
                                                                                 'lot/eligibility '
                                                                                 'constraints '
                                                                                 'declared but '
                                                                                 'execution not '
                                                                                 'simulated here'],
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
                                                     'frontend_capabilities': ['portfolio '
                                                                               'targets']},
 'PortfolioService.v1.getPortfolioReadModel': {'operation_id': 'PortfolioService.v1.getPortfolioReadModel',
                                               'version': '1.0.0',
                                               'kind': 'QUERY',
                                               'request_dto': {'name': 'GetPortfolioReadModelRequestV1',
                                                               'schema': {'type': 'object',
                                                                          'additionalProperties': False,
                                                                          'required': ['request_id',
                                                                                       'project_id',
                                                                                       'project_context_revision_id',
                                                                                       'expected_api_version',
                                                                                       'portfolio_version_id'],
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
                                                                                         'portfolio_version_id': {'type': 'string',
                                                                                                                  'description': 'Immutable '
                                                                                                                                 'portfolio '
                                                                                                                                 'version'}}}},
                                               'response_dto': {'name': 'GetPortfolioReadModelResponseV1',
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
                                                                                                                        'PortfolioReadModelV1; '
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
                                               'read_models': ['PortfolioReadModelV1'],
                                               'frontend_capabilities': ['weights Inspector']}}

class ValidateConstructionSpecRequestV1(ClosedDto):
    DTO_NAME = 'ValidateConstructionSpecRequestV1'
    OPERATION_ID = 'PortfolioService.v1.validateConstructionSpec'
    SCHEMA = METHOD_SPECS['PortfolioService.v1.validateConstructionSpec']['request_dto']['schema']

class ValidateConstructionSpecResponseV1(ClosedDto):
    DTO_NAME = 'ValidateConstructionSpecResponseV1'
    OPERATION_ID = 'PortfolioService.v1.validateConstructionSpec'
    SCHEMA = METHOD_SPECS['PortfolioService.v1.validateConstructionSpec']['response_dto']['schema']

class MaterializePortfolioTargetsRequestV1(ClosedDto):
    DTO_NAME = 'MaterializePortfolioTargetsRequestV1'
    OPERATION_ID = 'PortfolioService.v1.materializePortfolioTargets'
    SCHEMA = METHOD_SPECS['PortfolioService.v1.materializePortfolioTargets']['request_dto']['schema']

class MaterializePortfolioTargetsAcceptedV1(ClosedDto):
    DTO_NAME = 'MaterializePortfolioTargetsAcceptedV1'
    OPERATION_ID = 'PortfolioService.v1.materializePortfolioTargets'
    SCHEMA = METHOD_SPECS['PortfolioService.v1.materializePortfolioTargets']['response_dto']['schema']

class GetPortfolioReadModelRequestV1(ClosedDto):
    DTO_NAME = 'GetPortfolioReadModelRequestV1'
    OPERATION_ID = 'PortfolioService.v1.getPortfolioReadModel'
    SCHEMA = METHOD_SPECS['PortfolioService.v1.getPortfolioReadModel']['request_dto']['schema']

class GetPortfolioReadModelResponseV1(ClosedDto):
    DTO_NAME = 'GetPortfolioReadModelResponseV1'
    OPERATION_ID = 'PortfolioService.v1.getPortfolioReadModel'
    SCHEMA = METHOD_SPECS['PortfolioService.v1.getPortfolioReadModel']['response_dto']['schema']

OPERATION_IDS = ('PortfolioService.v1.validateConstructionSpec',
 'PortfolioService.v1.materializePortfolioTargets',
 'PortfolioService.v1.getPortfolioReadModel')
OPERATIONS = (
    OperationContract(
        operation_id='PortfolioService.v1.validateConstructionSpec',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ValidateConstructionSpecRequestV1,
        response_type=ValidateConstructionSpecResponseV1,
        metadata=METHOD_SPECS['PortfolioService.v1.validateConstructionSpec'],
    ),
    OperationContract(
        operation_id='PortfolioService.v1.materializePortfolioTargets',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=MaterializePortfolioTargetsRequestV1,
        response_type=MaterializePortfolioTargetsAcceptedV1,
        metadata=METHOD_SPECS['PortfolioService.v1.materializePortfolioTargets'],
    ),
    OperationContract(
        operation_id='PortfolioService.v1.getPortfolioReadModel',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetPortfolioReadModelRequestV1,
        response_type=GetPortfolioReadModelResponseV1,
        metadata=METHOD_SPECS['PortfolioService.v1.getPortfolioReadModel'],
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
 'ValidateConstructionSpecRequestV1',
 'ValidateConstructionSpecResponseV1',
 'MaterializePortfolioTargetsRequestV1',
 'MaterializePortfolioTargetsAcceptedV1',
 'GetPortfolioReadModelRequestV1',
 'GetPortfolioReadModelResponseV1')

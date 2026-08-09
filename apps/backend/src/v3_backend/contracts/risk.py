from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:risk:1.0.0'
SERVICE = 'RiskService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'RiskService.v1.buildRiskModel': {'operation_id': 'RiskService.v1.buildRiskModel',
                                   'version': '1.0.0',
                                   'kind': 'ASYNC_COMMAND',
                                   'request_dto': {'name': 'BuildRiskModelRequestV1',
                                                   'schema': {'type': 'object',
                                                              'additionalProperties': False,
                                                              'required': ['request_id',
                                                                           'project_id',
                                                                           'project_context_revision_id',
                                                                           'expected_api_version',
                                                                           'risk_model_spec_id',
                                                                           'snapshot_id',
                                                                           'universe_version_id',
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
                                                                             'risk_model_spec_id': {'type': 'string',
                                                                                                    'description': 'Pinned '
                                                                                                                   'transparent '
                                                                                                                   'A-share '
                                                                                                                   'model '
                                                                                                                   'spec'},
                                                                             'snapshot_id': {'type': 'string',
                                                                                             'description': 'Published '
                                                                                                            'immutable '
                                                                                                            'data '
                                                                                                            'snapshot '
                                                                                                            'identity',
                                                                                             'pattern': '^snp_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                             'universe_version_id': {'type': 'string',
                                                                                                     'description': 'Estimation '
                                                                                                                    'universe'},
                                                                             'idempotency_key': {'type': 'string',
                                                                                                 'description': 'Stable '
                                                                                                                'model '
                                                                                                                'key'}}}},
                                   'response_dto': {'name': 'BuildRiskModelAcceptedV1',
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
                                                      'run_identity_inputs': ['risk spec',
                                                                              'snapshot',
                                                                              'universe',
                                                                              'taxonomy',
                                                                              'estimation window'],
                                                      'artifact_outputs': ['RiskExposureParquet',
                                                                           'FactorCovarianceParquet',
                                                                           'SpecificRiskParquet',
                                                                           'RiskValidationReport'],
                                                      'cancel': 'COOPERATIVE',
                                                      'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                      'resume': 'FROM_DATE_CHECKPOINT',
                                                      'input_change': 'MUST_CREATE_NEW_RUN',
                                                      'attempt_rule': 'retry/resume always creates '
                                                                      'a new TaskAttempt; previous '
                                                                      'attempts are immutable'},
                                   'truth_pit_preconditions': ['industry taxonomy version pinned',
                                                               'PIT-safe inputs',
                                                               'B/F/D/Sigma validation passes '
                                                               'before publication'],
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
                                   'frontend_capabilities': ['RiskModelVersion']},
 'RiskService.v1.evaluatePortfolioRisk': {'operation_id': 'RiskService.v1.evaluatePortfolioRisk',
                                          'version': '1.0.0',
                                          'kind': 'ASYNC_COMMAND',
                                          'request_dto': {'name': 'EvaluatePortfolioRiskRequestV1',
                                                          'schema': {'type': 'object',
                                                                     'additionalProperties': False,
                                                                     'required': ['request_id',
                                                                                  'project_id',
                                                                                  'project_context_revision_id',
                                                                                  'expected_api_version',
                                                                                  'portfolio_version_id',
                                                                                  'risk_model_version_id',
                                                                                  'analysis_spec',
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
                                                                                    'portfolio_version_id': {'type': 'string',
                                                                                                             'description': 'Pinned '
                                                                                                                            'holdings/targets'},
                                                                                    'risk_model_version_id': {'type': 'string',
                                                                                                              'description': 'Published '
                                                                                                                             'risk '
                                                                                                                             'model'},
                                                                                    'analysis_spec': {'type': 'object',
                                                                                                      'description': 'Contribution, '
                                                                                                                     'VaR/ES '
                                                                                                                     'settings'},
                                                                                    'idempotency_key': {'type': 'string',
                                                                                                        'description': 'Stable '
                                                                                                                       'analysis '
                                                                                                                       'key'}}}},
                                          'response_dto': {'name': 'EvaluatePortfolioRiskAcceptedV1',
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
                                                             'run_identity_inputs': ['portfolio '
                                                                                     'hash',
                                                                                     'risk model '
                                                                                     'hash',
                                                                                     'analysis '
                                                                                     'spec'],
                                                             'artifact_outputs': ['RiskAnalysisParquet',
                                                                                  'RiskSummary'],
                                                             'cancel': 'COOPERATIVE',
                                                             'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                             'resume': 'NOT_SUPPORTED',
                                                             'input_change': 'MUST_CREATE_NEW_RUN',
                                                             'attempt_rule': 'retry/resume always '
                                                                             'creates a new '
                                                                             'TaskAttempt; '
                                                                             'previous attempts '
                                                                             'are immutable'},
                                          'truth_pit_preconditions': ['portfolio and risk model '
                                                                      'dates compatible'],
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
                                          'frontend_capabilities': ['risk contribution', 'VaR/ES']},
 'RiskService.v1.runStressTest': {'operation_id': 'RiskService.v1.runStressTest',
                                  'version': '1.0.0',
                                  'kind': 'ASYNC_COMMAND',
                                  'request_dto': {'name': 'RunStressTestRequestV1',
                                                  'schema': {'type': 'object',
                                                             'additionalProperties': False,
                                                             'required': ['request_id',
                                                                          'project_id',
                                                                          'project_context_revision_id',
                                                                          'expected_api_version',
                                                                          'portfolio_version_id',
                                                                          'risk_model_version_id',
                                                                          'scenario_set_artifact_id',
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
                                                                            'portfolio_version_id': {'type': 'string',
                                                                                                     'description': 'Portfolio '
                                                                                                                    'identity'},
                                                                            'risk_model_version_id': {'type': 'string',
                                                                                                      'description': 'Risk '
                                                                                                                     'model '
                                                                                                                     'identity'},
                                                                            'scenario_set_artifact_id': {'type': 'string',
                                                                                                         'description': 'Content-addressed '
                                                                                                                        'artifact '
                                                                                                                        'identity',
                                                                                                         'pattern': '^art_sha256_[0-9a-f]{64}$'},
                                                                            'idempotency_key': {'type': 'string',
                                                                                                'description': 'Stable '
                                                                                                               'stress '
                                                                                                               'key'}}}},
                                  'response_dto': {'name': 'RunStressTestAcceptedV1',
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
                                                     'run_identity_inputs': ['portfolio',
                                                                             'risk model',
                                                                             'scenario set'],
                                                     'artifact_outputs': ['StressResultParquet',
                                                                          'StressSummary'],
                                                     'cancel': 'COOPERATIVE',
                                                     'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                     'resume': 'FROM_SCENARIO_CHECKPOINT',
                                                     'input_change': 'MUST_CREATE_NEW_RUN',
                                                     'attempt_rule': 'retry/resume always creates '
                                                                     'a new TaskAttempt; previous '
                                                                     'attempts are immutable'},
                                  'truth_pit_preconditions': ['ProjectContextRevision exists and '
                                                              'is not superseded for this request'],
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
                                  'frontend_capabilities': ['stress testing']}}

class BuildRiskModelRequestV1(ClosedDto):
    DTO_NAME = 'BuildRiskModelRequestV1'
    OPERATION_ID = 'RiskService.v1.buildRiskModel'
    SCHEMA = METHOD_SPECS['RiskService.v1.buildRiskModel']['request_dto']['schema']

class BuildRiskModelAcceptedV1(ClosedDto):
    DTO_NAME = 'BuildRiskModelAcceptedV1'
    OPERATION_ID = 'RiskService.v1.buildRiskModel'
    SCHEMA = METHOD_SPECS['RiskService.v1.buildRiskModel']['response_dto']['schema']

class EvaluatePortfolioRiskRequestV1(ClosedDto):
    DTO_NAME = 'EvaluatePortfolioRiskRequestV1'
    OPERATION_ID = 'RiskService.v1.evaluatePortfolioRisk'
    SCHEMA = METHOD_SPECS['RiskService.v1.evaluatePortfolioRisk']['request_dto']['schema']

class EvaluatePortfolioRiskAcceptedV1(ClosedDto):
    DTO_NAME = 'EvaluatePortfolioRiskAcceptedV1'
    OPERATION_ID = 'RiskService.v1.evaluatePortfolioRisk'
    SCHEMA = METHOD_SPECS['RiskService.v1.evaluatePortfolioRisk']['response_dto']['schema']

class RunStressTestRequestV1(ClosedDto):
    DTO_NAME = 'RunStressTestRequestV1'
    OPERATION_ID = 'RiskService.v1.runStressTest'
    SCHEMA = METHOD_SPECS['RiskService.v1.runStressTest']['request_dto']['schema']

class RunStressTestAcceptedV1(ClosedDto):
    DTO_NAME = 'RunStressTestAcceptedV1'
    OPERATION_ID = 'RiskService.v1.runStressTest'
    SCHEMA = METHOD_SPECS['RiskService.v1.runStressTest']['response_dto']['schema']

OPERATION_IDS = ('RiskService.v1.buildRiskModel',
 'RiskService.v1.evaluatePortfolioRisk',
 'RiskService.v1.runStressTest')
OPERATIONS = (
    OperationContract(
        operation_id='RiskService.v1.buildRiskModel',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=BuildRiskModelRequestV1,
        response_type=BuildRiskModelAcceptedV1,
        metadata=METHOD_SPECS['RiskService.v1.buildRiskModel'],
    ),
    OperationContract(
        operation_id='RiskService.v1.evaluatePortfolioRisk',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=EvaluatePortfolioRiskRequestV1,
        response_type=EvaluatePortfolioRiskAcceptedV1,
        metadata=METHOD_SPECS['RiskService.v1.evaluatePortfolioRisk'],
    ),
    OperationContract(
        operation_id='RiskService.v1.runStressTest',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=RunStressTestRequestV1,
        response_type=RunStressTestAcceptedV1,
        metadata=METHOD_SPECS['RiskService.v1.runStressTest'],
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
 'BuildRiskModelRequestV1',
 'BuildRiskModelAcceptedV1',
 'EvaluatePortfolioRiskRequestV1',
 'EvaluatePortfolioRiskAcceptedV1',
 'RunStressTestRequestV1',
 'RunStressTestAcceptedV1')

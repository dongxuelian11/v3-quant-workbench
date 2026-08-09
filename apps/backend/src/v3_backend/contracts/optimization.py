from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:optimization:1.0.0'
SERVICE = 'OptimizationService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'OptimizationService.v1.compileConstraintSet': {'operation_id': 'OptimizationService.v1.compileConstraintSet',
                                                 'version': '1.0.0',
                                                 'kind': 'COMMAND',
                                                 'request_dto': {'name': 'CompileConstraintSetRequestV1',
                                                                 'schema': {'type': 'object',
                                                                            'additionalProperties': False,
                                                                            'required': ['request_id',
                                                                                         'project_id',
                                                                                         'project_context_revision_id',
                                                                                         'expected_api_version',
                                                                                         'constraint_draft',
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
                                                                                           'constraint_draft': {'type': 'object',
                                                                                                                'description': 'Typed '
                                                                                                                               'constraints, '
                                                                                                                               'bounds '
                                                                                                                               'and '
                                                                                                                               'priorities'},
                                                                                           'idempotency_key': {'type': 'string',
                                                                                                               'description': 'Stable '
                                                                                                                              'compile '
                                                                                                                              'key'}}}},
                                                 'response_dto': {'name': 'CompileConstraintSetResponseV1',
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
                                                                                                                          'ConstraintCompilationReadModelV1; '
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
                                                 'truth_pit_preconditions': ['conflicts and unit '
                                                                             'errors are reported; '
                                                                             'no silent '
                                                                             'relaxation'],
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
                                                 'read_models': ['ConstraintCompilationReadModelV1'],
                                                 'frontend_capabilities': ['constraint editor',
                                                                           'conflict diagnostics']},
 'OptimizationService.v1.solveOptimization': {'operation_id': 'OptimizationService.v1.solveOptimization',
                                              'version': '1.0.0',
                                              'kind': 'ASYNC_COMMAND',
                                              'request_dto': {'name': 'SolveOptimizationRequestV1',
                                                              'schema': {'type': 'object',
                                                                         'additionalProperties': False,
                                                                         'required': ['request_id',
                                                                                      'project_id',
                                                                                      'project_context_revision_id',
                                                                                      'expected_api_version',
                                                                                      'optimization_problem_id',
                                                                                      'solver_profile_id',
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
                                                                                        'optimization_problem_id': {'type': 'string',
                                                                                                                    'description': 'Immutable '
                                                                                                                                   'problem '
                                                                                                                                   'with '
                                                                                                                                   'objective '
                                                                                                                                   'and '
                                                                                                                                   'all '
                                                                                                                                   'input '
                                                                                                                                   'versions'},
                                                                                        'solver_profile_id': {'type': 'string',
                                                                                                              'description': 'Explicit '
                                                                                                                             'admitted '
                                                                                                                             'solver/tolerance '
                                                                                                                             'profile'},
                                                                                        'idempotency_key': {'type': 'string',
                                                                                                            'description': 'Stable '
                                                                                                                           'solve '
                                                                                                                           'key'}}}},
                                              'response_dto': {'name': 'SolveOptimizationAcceptedV1',
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
                                                                 'run_identity_inputs': ['problem '
                                                                                         'hash',
                                                                                         'constraint '
                                                                                         'set',
                                                                                         'risk '
                                                                                         'model',
                                                                                         'expected '
                                                                                         'returns',
                                                                                         'solver '
                                                                                         'profile'],
                                                                 'artifact_outputs': ['OptimizationSolutionParquet',
                                                                                      'SolverLog',
                                                                                      'ResidualValidationReport'],
                                                                 'cancel': 'COOPERATIVE_THEN_TERMINATE_SOLVER',
                                                                 'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                                 'resume': 'SOLVER_PROFILE_DEPENDENT_EXPLICIT_ONLY',
                                                                 'input_change': 'MUST_CREATE_NEW_RUN',
                                                                 'attempt_rule': 'retry/resume '
                                                                                 'always creates a '
                                                                                 'new TaskAttempt; '
                                                                                 'previous '
                                                                                 'attempts are '
                                                                                 'immutable'},
                                              'truth_pit_preconditions': ['solver admitted',
                                                                          'all bound inputs '
                                                                          'immutable',
                                                                          'problem units and '
                                                                          'dimensions validate'],
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
                                                         'INTERNAL_ERROR',
                                                         'INFEASIBLE',
                                                         'UNBOUNDED',
                                                         'SOLVER_FAILED',
                                                         'RESIDUAL_VALIDATION_FAILED'],
                                              'provenance_required': ['request_actor',
                                                                      'project_context_revision_id',
                                                                      'operation_id',
                                                                      'contract_version',
                                                                      'input_object_ids',
                                                                      'input_content_hashes',
                                                                      'environment_profile_id',
                                                                      'code_version'],
                                              'read_models': [],
                                              'frontend_capabilities': ['optimization state and '
                                                                        'weights']},
 'OptimizationService.v1.getOptimizationSolution': {'operation_id': 'OptimizationService.v1.getOptimizationSolution',
                                                    'version': '1.0.0',
                                                    'kind': 'QUERY',
                                                    'request_dto': {'name': 'GetOptimizationSolutionRequestV1',
                                                                    'schema': {'type': 'object',
                                                                               'additionalProperties': False,
                                                                               'required': ['request_id',
                                                                                            'project_id',
                                                                                            'project_context_revision_id',
                                                                                            'expected_api_version',
                                                                                            'optimization_solution_id'],
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
                                                                                              'optimization_solution_id': {'type': 'string',
                                                                                                                           'description': 'Immutable '
                                                                                                                                          'solution '
                                                                                                                                          'identity'}}}},
                                                    'response_dto': {'name': 'GetOptimizationSolutionResponseV1',
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
                                                                                                                             'OptimizationSolutionReadModelV1; '
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
                                                    'truth_pit_preconditions': ['non-optimal '
                                                                                'states expose no '
                                                                                'fake weights',
                                                                                'FORMAL requires '
                                                                                'independent '
                                                                                'residual '
                                                                                'validation PASS'],
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
                                                    'read_models': ['OptimizationSolutionReadModelV1'],
                                                    'frontend_capabilities': ['optimization '
                                                                              'Inspector']}}

class CompileConstraintSetRequestV1(ClosedDto):
    DTO_NAME = 'CompileConstraintSetRequestV1'
    OPERATION_ID = 'OptimizationService.v1.compileConstraintSet'
    SCHEMA = METHOD_SPECS['OptimizationService.v1.compileConstraintSet']['request_dto']['schema']

class CompileConstraintSetResponseV1(ClosedDto):
    DTO_NAME = 'CompileConstraintSetResponseV1'
    OPERATION_ID = 'OptimizationService.v1.compileConstraintSet'
    SCHEMA = METHOD_SPECS['OptimizationService.v1.compileConstraintSet']['response_dto']['schema']

class SolveOptimizationRequestV1(ClosedDto):
    DTO_NAME = 'SolveOptimizationRequestV1'
    OPERATION_ID = 'OptimizationService.v1.solveOptimization'
    SCHEMA = METHOD_SPECS['OptimizationService.v1.solveOptimization']['request_dto']['schema']

class SolveOptimizationAcceptedV1(ClosedDto):
    DTO_NAME = 'SolveOptimizationAcceptedV1'
    OPERATION_ID = 'OptimizationService.v1.solveOptimization'
    SCHEMA = METHOD_SPECS['OptimizationService.v1.solveOptimization']['response_dto']['schema']

class GetOptimizationSolutionRequestV1(ClosedDto):
    DTO_NAME = 'GetOptimizationSolutionRequestV1'
    OPERATION_ID = 'OptimizationService.v1.getOptimizationSolution'
    SCHEMA = METHOD_SPECS['OptimizationService.v1.getOptimizationSolution']['request_dto']['schema']

class GetOptimizationSolutionResponseV1(ClosedDto):
    DTO_NAME = 'GetOptimizationSolutionResponseV1'
    OPERATION_ID = 'OptimizationService.v1.getOptimizationSolution'
    SCHEMA = METHOD_SPECS['OptimizationService.v1.getOptimizationSolution']['response_dto']['schema']

OPERATION_IDS = ('OptimizationService.v1.compileConstraintSet',
 'OptimizationService.v1.solveOptimization',
 'OptimizationService.v1.getOptimizationSolution')
OPERATIONS = (
    OperationContract(
        operation_id='OptimizationService.v1.compileConstraintSet',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=CompileConstraintSetRequestV1,
        response_type=CompileConstraintSetResponseV1,
        metadata=METHOD_SPECS['OptimizationService.v1.compileConstraintSet'],
    ),
    OperationContract(
        operation_id='OptimizationService.v1.solveOptimization',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=SolveOptimizationRequestV1,
        response_type=SolveOptimizationAcceptedV1,
        metadata=METHOD_SPECS['OptimizationService.v1.solveOptimization'],
    ),
    OperationContract(
        operation_id='OptimizationService.v1.getOptimizationSolution',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetOptimizationSolutionRequestV1,
        response_type=GetOptimizationSolutionResponseV1,
        metadata=METHOD_SPECS['OptimizationService.v1.getOptimizationSolution'],
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
 'CompileConstraintSetRequestV1',
 'CompileConstraintSetResponseV1',
 'SolveOptimizationRequestV1',
 'SolveOptimizationAcceptedV1',
 'GetOptimizationSolutionRequestV1',
 'GetOptimizationSolutionResponseV1')

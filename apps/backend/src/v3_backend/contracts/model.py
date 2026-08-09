from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:model:1.0.0'
SERVICE = 'ModelService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'ModelService.v1.validateTrainingSpec': {'operation_id': 'ModelService.v1.validateTrainingSpec',
                                          'version': '1.0.0',
                                          'kind': 'QUERY',
                                          'request_dto': {'name': 'ValidateTrainingSpecRequestV1',
                                                          'schema': {'type': 'object',
                                                                     'additionalProperties': False,
                                                                     'required': ['request_id',
                                                                                  'project_id',
                                                                                  'project_context_revision_id',
                                                                                  'expected_api_version',
                                                                                  'training_spec'],
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
                                                                                    'training_spec': {'type': 'object',
                                                                                                      'description': 'Family, '
                                                                                                                     'hyperparameters, '
                                                                                                                     'environment, '
                                                                                                                     'evaluation '
                                                                                                                     'and '
                                                                                                                     'seed '
                                                                                                                     'contract'}}}},
                                          'response_dto': {'name': 'ValidateTrainingSpecResponseV1',
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
                                                                                                                   'TrainingSpecValidationV1; '
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
                                          'truth_pit_preconditions': ['model family is one of '
                                                                      'seven admitted families',
                                                                      'CPU FORMAL environment '
                                                                      'available',
                                                                      'safe artifact format '
                                                                      'admitted'],
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
                                          'read_models': ['TrainingSpecValidationV1'],
                                          'frontend_capabilities': ['seven model families']},
 'ModelService.v1.trainModel': {'operation_id': 'ModelService.v1.trainModel',
                                'version': '1.0.0',
                                'kind': 'ASYNC_COMMAND',
                                'request_dto': {'name': 'TrainModelRequestV1',
                                                'schema': {'type': 'object',
                                                           'additionalProperties': False,
                                                           'required': ['request_id',
                                                                        'project_id',
                                                                        'project_context_revision_id',
                                                                        'expected_api_version',
                                                                        'dataset_version_id',
                                                                        'training_spec_id',
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
                                                                          'dataset_version_id': {'type': 'string',
                                                                                                 'description': 'Leakage-cleared '
                                                                                                                'immutable '
                                                                                                                'dataset'},
                                                                          'training_spec_id': {'type': 'string',
                                                                                               'description': 'Validated '
                                                                                                              'training '
                                                                                                              'spec'},
                                                                          'idempotency_key': {'type': 'string',
                                                                                              'description': 'Stable '
                                                                                                             'training '
                                                                                                             'key'}}}},
                                'response_dto': {'name': 'TrainModelAcceptedV1',
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
                                                   'run_identity_inputs': ['dataset hash',
                                                                           'training spec hash',
                                                                           'environment profile',
                                                                           'seed',
                                                                           'code version'],
                                                   'artifact_outputs': ['SafeModelArtifact',
                                                                        'TrainingMetricsParquet',
                                                                        'ModelDiagnostics',
                                                                        'ModelCard'],
                                                   'cancel': 'CHECKPOINT_THEN_COOPERATIVE_TERMINATE',
                                                   'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                   'resume': 'FROM_COMPATIBLE_CHECKPOINT',
                                                   'input_change': 'MUST_CREATE_NEW_RUN',
                                                   'attempt_rule': 'retry/resume always creates a '
                                                                   'new TaskAttempt; previous '
                                                                   'attempts are immutable'},
                                'truth_pit_preconditions': ['leakage audit PASS',
                                                            'environment profile admitted',
                                                            'final test unavailable to training'],
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
                                'frontend_capabilities': ['model training', 'checkpoint']},
 'ModelService.v1.generatePredictionSignals': {'operation_id': 'ModelService.v1.generatePredictionSignals',
                                               'version': '1.0.0',
                                               'kind': 'ASYNC_COMMAND',
                                               'request_dto': {'name': 'GeneratePredictionSignalsRequestV1',
                                                               'schema': {'type': 'object',
                                                                          'additionalProperties': False,
                                                                          'required': ['request_id',
                                                                                       'project_id',
                                                                                       'project_context_revision_id',
                                                                                       'expected_api_version',
                                                                                       'model_version_id',
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
                                                                                         'model_version_id': {'type': 'string',
                                                                                                              'description': 'Immutable '
                                                                                                                             'model '
                                                                                                                             'version'},
                                                                                         'dataset_version_id': {'type': 'string',
                                                                                                                'description': 'Prediction '
                                                                                                                               'dataset '
                                                                                                                               'version'},
                                                                                         'idempotency_key': {'type': 'string',
                                                                                                             'description': 'Stable '
                                                                                                                            'signal '
                                                                                                                            'key'}}}},
                                               'response_dto': {'name': 'GeneratePredictionSignalsAcceptedV1',
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
                                                                  'run_identity_inputs': ['model '
                                                                                          'hash',
                                                                                          'dataset '
                                                                                          'hash',
                                                                                          'inference '
                                                                                          'environment'],
                                                                  'artifact_outputs': ['PredictionSignalParquet',
                                                                                       'InferenceDiagnostics'],
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
                                               'truth_pit_preconditions': ['safe model loader '
                                                                           'accepts format',
                                                                           'feature schema exact '
                                                                           'match',
                                                                           'PIT cutoff preserved'],
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
                                               'frontend_capabilities': ['PredictionSignalVersion']},
 'ModelService.v1.compareModelVersions': {'operation_id': 'ModelService.v1.compareModelVersions',
                                          'version': '1.0.0',
                                          'kind': 'QUERY',
                                          'request_dto': {'name': 'CompareModelVersionsRequestV1',
                                                          'schema': {'type': 'object',
                                                                     'additionalProperties': False,
                                                                     'required': ['request_id',
                                                                                  'project_id',
                                                                                  'project_context_revision_id',
                                                                                  'expected_api_version',
                                                                                  'model_version_ids'],
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
                                                                                    'model_version_ids': {'type': 'array',
                                                                                                          'description': 'Immutable '
                                                                                                                         'models',
                                                                                                          'items': {'type': 'string'},
                                                                                                          'minItems': 2}}}},
                                          'response_dto': {'name': 'CompareModelVersionsResponseV1',
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
                                                                                                                   'ModelComparisonReadModelV1; '
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
                                          'read_models': ['ModelComparisonReadModelV1'],
                                          'frontend_capabilities': ['MLflow-style run comparison']}}

class ValidateTrainingSpecRequestV1(ClosedDto):
    DTO_NAME = 'ValidateTrainingSpecRequestV1'
    OPERATION_ID = 'ModelService.v1.validateTrainingSpec'
    SCHEMA = METHOD_SPECS['ModelService.v1.validateTrainingSpec']['request_dto']['schema']

class ValidateTrainingSpecResponseV1(ClosedDto):
    DTO_NAME = 'ValidateTrainingSpecResponseV1'
    OPERATION_ID = 'ModelService.v1.validateTrainingSpec'
    SCHEMA = METHOD_SPECS['ModelService.v1.validateTrainingSpec']['response_dto']['schema']

class TrainModelRequestV1(ClosedDto):
    DTO_NAME = 'TrainModelRequestV1'
    OPERATION_ID = 'ModelService.v1.trainModel'
    SCHEMA = METHOD_SPECS['ModelService.v1.trainModel']['request_dto']['schema']

class TrainModelAcceptedV1(ClosedDto):
    DTO_NAME = 'TrainModelAcceptedV1'
    OPERATION_ID = 'ModelService.v1.trainModel'
    SCHEMA = METHOD_SPECS['ModelService.v1.trainModel']['response_dto']['schema']

class GeneratePredictionSignalsRequestV1(ClosedDto):
    DTO_NAME = 'GeneratePredictionSignalsRequestV1'
    OPERATION_ID = 'ModelService.v1.generatePredictionSignals'
    SCHEMA = METHOD_SPECS['ModelService.v1.generatePredictionSignals']['request_dto']['schema']

class GeneratePredictionSignalsAcceptedV1(ClosedDto):
    DTO_NAME = 'GeneratePredictionSignalsAcceptedV1'
    OPERATION_ID = 'ModelService.v1.generatePredictionSignals'
    SCHEMA = METHOD_SPECS['ModelService.v1.generatePredictionSignals']['response_dto']['schema']

class CompareModelVersionsRequestV1(ClosedDto):
    DTO_NAME = 'CompareModelVersionsRequestV1'
    OPERATION_ID = 'ModelService.v1.compareModelVersions'
    SCHEMA = METHOD_SPECS['ModelService.v1.compareModelVersions']['request_dto']['schema']

class CompareModelVersionsResponseV1(ClosedDto):
    DTO_NAME = 'CompareModelVersionsResponseV1'
    OPERATION_ID = 'ModelService.v1.compareModelVersions'
    SCHEMA = METHOD_SPECS['ModelService.v1.compareModelVersions']['response_dto']['schema']

OPERATION_IDS = ('ModelService.v1.validateTrainingSpec',
 'ModelService.v1.trainModel',
 'ModelService.v1.generatePredictionSignals',
 'ModelService.v1.compareModelVersions')
OPERATIONS = (
    OperationContract(
        operation_id='ModelService.v1.validateTrainingSpec',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ValidateTrainingSpecRequestV1,
        response_type=ValidateTrainingSpecResponseV1,
        metadata=METHOD_SPECS['ModelService.v1.validateTrainingSpec'],
    ),
    OperationContract(
        operation_id='ModelService.v1.trainModel',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=TrainModelRequestV1,
        response_type=TrainModelAcceptedV1,
        metadata=METHOD_SPECS['ModelService.v1.trainModel'],
    ),
    OperationContract(
        operation_id='ModelService.v1.generatePredictionSignals',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=GeneratePredictionSignalsRequestV1,
        response_type=GeneratePredictionSignalsAcceptedV1,
        metadata=METHOD_SPECS['ModelService.v1.generatePredictionSignals'],
    ),
    OperationContract(
        operation_id='ModelService.v1.compareModelVersions',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=CompareModelVersionsRequestV1,
        response_type=CompareModelVersionsResponseV1,
        metadata=METHOD_SPECS['ModelService.v1.compareModelVersions'],
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
 'ValidateTrainingSpecRequestV1',
 'ValidateTrainingSpecResponseV1',
 'TrainModelRequestV1',
 'TrainModelAcceptedV1',
 'GeneratePredictionSignalsRequestV1',
 'GeneratePredictionSignalsAcceptedV1',
 'CompareModelVersionsRequestV1',
 'CompareModelVersionsResponseV1')

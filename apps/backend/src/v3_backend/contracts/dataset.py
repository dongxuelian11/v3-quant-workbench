from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:dataset:1.0.0'
SERVICE = 'DatasetService'
API_VERSION = '1.0.0'
METHOD_SPECS = {'DatasetService.v1.validateDatasetSpec': {'operation_id': 'DatasetService.v1.validateDatasetSpec',
                                           'version': '1.0.0',
                                           'kind': 'QUERY',
                                           'request_dto': {'name': 'ValidateDatasetSpecRequestV1',
                                                           'schema': {'type': 'object',
                                                                      'additionalProperties': False,
                                                                      'required': ['request_id',
                                                                                   'project_id',
                                                                                   'project_context_revision_id',
                                                                                   'expected_api_version',
                                                                                   'dataset_spec'],
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
                                                                                     'dataset_spec': {'type': 'object',
                                                                                                      'description': 'FeatureSet, '
                                                                                                                     'LabelSpec, '
                                                                                                                     'SplitSpec, '
                                                                                                                     'purge/embargo '
                                                                                                                     'and '
                                                                                                                     'preprocessing '
                                                                                                                     'contract'}}}},
                                           'response_dto': {'name': 'ValidateDatasetSpecResponseV1',
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
                                                                                                                    'DatasetSpecValidationV1; '
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
                                           'truth_pit_preconditions': ['random time split '
                                                                       'forbidden in FORMAL',
                                                                       'preprocessors declare fit '
                                                                       'scope TRAIN_ONLY',
                                                                       'HPO final-test isolation '
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
                                           'read_models': ['DatasetSpecValidationV1'],
                                           'frontend_capabilities': ['DatasetVersion / Label / '
                                                                     'SplitPlan']},
 'DatasetService.v1.materializeDataset': {'operation_id': 'DatasetService.v1.materializeDataset',
                                          'version': '1.0.0',
                                          'kind': 'ASYNC_COMMAND',
                                          'request_dto': {'name': 'MaterializeDatasetRequestV1',
                                                          'schema': {'type': 'object',
                                                                     'additionalProperties': False,
                                                                     'required': ['request_id',
                                                                                  'project_id',
                                                                                  'project_context_revision_id',
                                                                                  'expected_api_version',
                                                                                  'dataset_spec_id',
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
                                                                                    'dataset_spec_id': {'type': 'string',
                                                                                                        'description': 'Immutable '
                                                                                                                       'validated '
                                                                                                                       'spec'},
                                                                                    'snapshot_id': {'type': 'string',
                                                                                                    'description': 'Published '
                                                                                                                   'immutable '
                                                                                                                   'data '
                                                                                                                   'snapshot '
                                                                                                                   'identity',
                                                                                                    'pattern': '^snp_[0-9A-HJKMNP-TV-Z]{26}$'},
                                                                                    'universe_version_id': {'type': 'string',
                                                                                                            'description': 'Pinned '
                                                                                                                           'universe '
                                                                                                                           'version'},
                                                                                    'idempotency_key': {'type': 'string',
                                                                                                        'description': 'Stable '
                                                                                                                       'materialization '
                                                                                                                       'key'}}}},
                                          'response_dto': {'name': 'MaterializeDatasetAcceptedV1',
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
                                                             'run_identity_inputs': ['dataset spec '
                                                                                     'hash',
                                                                                     'snapshot_id',
                                                                                     'universe '
                                                                                     'version',
                                                                                     'environment '
                                                                                     'profile'],
                                                             'artifact_outputs': ['DatasetParquetManifest',
                                                                                  'LeakageAuditReport',
                                                                                  'DatasetStatistics'],
                                                             'cancel': 'COOPERATIVE',
                                                             'retry': 'NEW_ATTEMPT_SAME_RUN',
                                                             'resume': 'FROM_SPLIT_PARTITION_CHECKPOINT',
                                                             'input_change': 'MUST_CREATE_NEW_RUN',
                                                             'attempt_rule': 'retry/resume always '
                                                                             'creates a new '
                                                                             'TaskAttempt; '
                                                                             'previous attempts '
                                                                             'are immutable'},
                                          'truth_pit_preconditions': ['snapshot PUBLISHED',
                                                                      'all feature/label rows obey '
                                                                      'available_time <= sample '
                                                                      'decision time',
                                                                      'leakage audit must pass '
                                                                      'before publish'],
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
                                          'frontend_capabilities': ['DatasetVersion', 'SplitPlan']},
 'DatasetService.v1.getDatasetVersion': {'operation_id': 'DatasetService.v1.getDatasetVersion',
                                         'version': '1.0.0',
                                         'kind': 'QUERY',
                                         'request_dto': {'name': 'GetDatasetVersionRequestV1',
                                                         'schema': {'type': 'object',
                                                                    'additionalProperties': False,
                                                                    'required': ['request_id',
                                                                                 'project_id',
                                                                                 'project_context_revision_id',
                                                                                 'expected_api_version',
                                                                                 'dataset_version_id'],
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
                                                                                                          'description': 'Immutable '
                                                                                                                         'dataset '
                                                                                                                         'version'}}}},
                                         'response_dto': {'name': 'GetDatasetVersionResponseV1',
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
                                                                                                                  'DatasetVersionReadModelV1; '
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
                                                                     'exists and is not superseded '
                                                                     'for this request'],
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
                                         'read_models': ['DatasetVersionReadModelV1'],
                                         'frontend_capabilities': ['dataset detail']}}

class ValidateDatasetSpecRequestV1(ClosedDto):
    DTO_NAME = 'ValidateDatasetSpecRequestV1'
    OPERATION_ID = 'DatasetService.v1.validateDatasetSpec'
    SCHEMA = METHOD_SPECS['DatasetService.v1.validateDatasetSpec']['request_dto']['schema']

class ValidateDatasetSpecResponseV1(ClosedDto):
    DTO_NAME = 'ValidateDatasetSpecResponseV1'
    OPERATION_ID = 'DatasetService.v1.validateDatasetSpec'
    SCHEMA = METHOD_SPECS['DatasetService.v1.validateDatasetSpec']['response_dto']['schema']

class MaterializeDatasetRequestV1(ClosedDto):
    DTO_NAME = 'MaterializeDatasetRequestV1'
    OPERATION_ID = 'DatasetService.v1.materializeDataset'
    SCHEMA = METHOD_SPECS['DatasetService.v1.materializeDataset']['request_dto']['schema']

class MaterializeDatasetAcceptedV1(ClosedDto):
    DTO_NAME = 'MaterializeDatasetAcceptedV1'
    OPERATION_ID = 'DatasetService.v1.materializeDataset'
    SCHEMA = METHOD_SPECS['DatasetService.v1.materializeDataset']['response_dto']['schema']

class GetDatasetVersionRequestV1(ClosedDto):
    DTO_NAME = 'GetDatasetVersionRequestV1'
    OPERATION_ID = 'DatasetService.v1.getDatasetVersion'
    SCHEMA = METHOD_SPECS['DatasetService.v1.getDatasetVersion']['request_dto']['schema']

class GetDatasetVersionResponseV1(ClosedDto):
    DTO_NAME = 'GetDatasetVersionResponseV1'
    OPERATION_ID = 'DatasetService.v1.getDatasetVersion'
    SCHEMA = METHOD_SPECS['DatasetService.v1.getDatasetVersion']['response_dto']['schema']

OPERATION_IDS = ('DatasetService.v1.validateDatasetSpec',
 'DatasetService.v1.materializeDataset',
 'DatasetService.v1.getDatasetVersion')
OPERATIONS = (
    OperationContract(
        operation_id='DatasetService.v1.validateDatasetSpec',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ValidateDatasetSpecRequestV1,
        response_type=ValidateDatasetSpecResponseV1,
        metadata=METHOD_SPECS['DatasetService.v1.validateDatasetSpec'],
    ),
    OperationContract(
        operation_id='DatasetService.v1.materializeDataset',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.ASYNC_COMMAND,
        request_type=MaterializeDatasetRequestV1,
        response_type=MaterializeDatasetAcceptedV1,
        metadata=METHOD_SPECS['DatasetService.v1.materializeDataset'],
    ),
    OperationContract(
        operation_id='DatasetService.v1.getDatasetVersion',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=GetDatasetVersionRequestV1,
        response_type=GetDatasetVersionResponseV1,
        metadata=METHOD_SPECS['DatasetService.v1.getDatasetVersion'],
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
 'ValidateDatasetSpecRequestV1',
 'ValidateDatasetSpecResponseV1',
 'MaterializeDatasetRequestV1',
 'MaterializeDatasetAcceptedV1',
 'GetDatasetVersionRequestV1',
 'GetDatasetVersionResponseV1')

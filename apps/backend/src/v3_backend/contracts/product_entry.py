"""ProductEntryService ASL contract: canonical research entry operations.

Bounded, versioned, non-P0 contract expansion for V1 Product Entry.  The two
project-scoped operations below are the only public surface added by the
Product Entry task; projectless bootstrap (createProject / listProjects) is a
separate narrow runtime control protocol (see runtime/product_entry.py) and is
deliberately NOT an ASL operation because every ASL request envelope is
project-bound by frozen design.

listBacktestRunSpecs discovers durable, project-owned canonical BacktestRunSpec
references and verifies actual artifact bytes before listing them executable.

importResearchPackage imports an explicitly user-selected V3 research package
(closed manifest + actual payload bytes) after full hash/identity/owner-binding
verification.  The request carries the manifest and bounded payload files; the
caller can never inject numeric financial truth (prices/returns/weights/NAV)
that the backend would trust - every numeric payload inside the package is
re-verified against canonical owners exactly as a locally authored one.
"""

from __future__ import annotations

from .common.dto import ClosedDto
from .common.operation import OperationContract, OperationKind, ServiceContract

CONTRACT_ID = 'urn:v3:asl:product_entry:1.0.0'
SERVICE = 'ProductEntryService'
API_VERSION = '1.0.0'

_PRJ = r'^prj_[0-9A-HJKMNP-TV-Z]{26}$'
_PCR = r'^pcr_[0-9A-HJKMNP-TV-Z]{26}$'
_BTRS = r'^btrs_sha256_[0-9a-f]{64}$'
_ART = r'^art_sha256_[0-9a-f]{64}$'
_HEX64 = r'^[0-9a-f]{64}$'
# Single-segment relative file names only; the importer rejects anything else.
_PKG_PATH = r'^[a-z0-9][a-z0-9._-]{0,63}$'

# Bounded package transfer limits (well inside the 1 MiB frame budget).
MAX_PACKAGE_FILES = 64
MAX_PACKAGE_FILE_BYTES = 262144
MAX_PACKAGE_TOTAL_BYTES = 786432

METHOD_SPECS = {
    'ProductEntryService.v1.listBacktestRunSpecs': {
        'operation_id': 'ProductEntryService.v1.listBacktestRunSpecs',
        'version': '1.0.0',
        'kind': 'QUERY',
        'request_dto': {
            'name': 'ListBacktestRunSpecsRequestV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'project_id', 'project_context_revision_id', 'expected_api_version'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical project identity', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Canonical project context revision identity', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact ASL major.minor expected by caller', 'const': '1.0'},
                    'page': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                            'after_run_spec_id': {'type': 'string', 'pattern': _BTRS},
                        },
                    },
                },
            },
        },
        'response_dto': {
            'name': 'ListBacktestRunSpecsResponseV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'description': 'Explicit capability truth', 'enum': ['FORMAL', 'DEMO', 'UNAVAILABLE']},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': ['read_model_version', 'specs', 'has_more'],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry/1.0'},
                            'specs': {
                                'type': 'array',
                                'maxItems': 100,
                                'items': {
                                    'type': 'object',
                                    'additionalProperties': False,
                                    'required': [
                                        'run_spec_id', 'artifact_id', 'content_sha256',
                                        'project_context_revision_id', 'engine_version',
                                        'created_at', 'execution_adapter_version_id', 'status',
                                    ],
                                    'properties': {
                                        'run_spec_id': {'type': 'string', 'pattern': _BTRS},
                                        'artifact_id': {'type': 'string', 'pattern': _ART},
                                        'content_sha256': {'type': 'string', 'pattern': _HEX64},
                                        'project_context_revision_id': {'type': 'string', 'pattern': _PCR},
                                        'engine_version': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                                        'created_at': {'type': 'string', 'format': 'date-time'},
                                        'execution_adapter_version_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                                        'status': {'type': 'string', 'enum': ['EXECUTABLE', 'UNAVAILABLE']},
                                        'diagnostic': {'type': 'string', 'maxLength': 500},
                                    },
                                },
                            },
                            'has_more': {'type': 'boolean'},
                        },
                    },
                },
            },
        },
    },
    'ProductEntryService.v1.importResearchPackage': {
        'operation_id': 'ProductEntryService.v1.importResearchPackage',
        'version': '1.0.0',
        'kind': 'COMMAND',
        'request_dto': {
            'name': 'ImportResearchPackageRequestV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'project_id', 'project_context_revision_id', 'expected_api_version', 'idempotency_key', 'manifest', 'files'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Transport deduplication identity', 'format': 'uuid'},
                    'project_id': {'type': 'string', 'description': 'Canonical project that will own the imported run spec', 'pattern': _PRJ},
                    'project_context_revision_id': {'type': 'string', 'description': 'Current canonical context revision of the target project', 'pattern': _PCR},
                    'expected_api_version': {'type': 'string', 'description': 'Exact ASL major.minor expected by caller', 'const': '1.0'},
                    'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 200, 'description': 'Idempotency key scoped to operation + project'},
                    'manifest': {
                        'type': 'object',
                        'description': 'Closed v3.research-package/1.0.0 manifest (strictly validated by the runtime importer)',
                    },
                    'files': {
                        'type': 'array',
                        'minItems': 1,
                        'maxItems': MAX_PACKAGE_FILES,
                        'items': {
                            'type': 'object',
                            'additionalProperties': False,
                            'required': ['path', 'sha256', 'byte_size', 'payload_base64'],
                            'properties': {
                                'path': {'type': 'string', 'pattern': _PKG_PATH, 'description': 'Relative package file name'},
                                'sha256': {'type': 'string', 'pattern': _HEX64, 'description': 'Declared SHA-256 of the actual payload bytes'},
                                'byte_size': {'type': 'integer', 'minimum': 1, 'maximum': MAX_PACKAGE_FILE_BYTES},
                                'payload_base64': {'type': 'string', 'minLength': 4, 'maxLength': 349526, 'description': 'Actual payload bytes (base64)'},
                            },
                        },
                    },
                },
            },
        },
        'response_dto': {
            'name': 'ImportResearchPackageResponseV1',
            'schema': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['request_id', 'truth_state', 'read_model'],
                'properties': {
                    'request_id': {'type': 'string', 'description': 'Echoed request identity', 'format': 'uuid'},
                    'truth_state': {'type': 'string', 'description': 'Explicit capability truth', 'enum': ['FORMAL', 'DEMO', 'UNAVAILABLE']},
                    'read_model': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': [
                            'read_model_version',
                            'run_spec_id', 'run_spec_artifact_id', 'context_artifact_id',
                            'already_imported', 'source_project_id', 'imported_at',
                        ],
                        'properties': {
                            'read_model_version': {'type': 'string', 'const': 'v3.product-entry/1.0'},
                            'run_spec_id': {'type': 'string', 'pattern': _BTRS},
                            'run_spec_artifact_id': {'type': 'string', 'pattern': _ART},
                            'context_artifact_id': {'type': 'string', 'pattern': _ART},
                            'already_imported': {'type': 'boolean', 'description': 'True when the same package was already imported (idempotent replay)'},
                            'source_project_id': {'type': 'string', 'pattern': _PRJ, 'description': 'Canonical source project identity carried by the package provenance'},
                            'imported_at': {'type': 'string', 'format': 'date-time'},
                        },
                    },
                },
            },
        },
    },
}


class ListBacktestRunSpecsRequestV1(ClosedDto):
    DTO_NAME = 'ListBacktestRunSpecsRequestV1'
    OPERATION_ID = 'ProductEntryService.v1.listBacktestRunSpecs'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.listBacktestRunSpecs']['request_dto']['schema']


class ListBacktestRunSpecsResponseV1(ClosedDto):
    DTO_NAME = 'ListBacktestRunSpecsResponseV1'
    OPERATION_ID = 'ProductEntryService.v1.listBacktestRunSpecs'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.listBacktestRunSpecs']['response_dto']['schema']


class ImportResearchPackageRequestV1(ClosedDto):
    DTO_NAME = 'ImportResearchPackageRequestV1'
    OPERATION_ID = 'ProductEntryService.v1.importResearchPackage'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.importResearchPackage']['request_dto']['schema']


class ImportResearchPackageResponseV1(ClosedDto):
    DTO_NAME = 'ImportResearchPackageResponseV1'
    OPERATION_ID = 'ProductEntryService.v1.importResearchPackage'
    SCHEMA = METHOD_SPECS['ProductEntryService.v1.importResearchPackage']['response_dto']['schema']


OPERATION_IDS = (
    'ProductEntryService.v1.listBacktestRunSpecs',
    'ProductEntryService.v1.importResearchPackage',
)
OPERATIONS = (
    OperationContract(
        operation_id='ProductEntryService.v1.listBacktestRunSpecs',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.QUERY,
        request_type=ListBacktestRunSpecsRequestV1,
        response_type=ListBacktestRunSpecsResponseV1,
        metadata=METHOD_SPECS['ProductEntryService.v1.listBacktestRunSpecs'],
    ),
    OperationContract(
        operation_id='ProductEntryService.v1.importResearchPackage',
        service=SERVICE,
        version='1.0.0',
        kind=OperationKind.COMMAND,
        request_type=ImportResearchPackageRequestV1,
        response_type=ImportResearchPackageResponseV1,
        metadata=METHOD_SPECS['ProductEntryService.v1.importResearchPackage'],
    ),
)
CONTRACT = ServiceContract(
    contract_id=CONTRACT_ID,
    service=SERVICE,
    api_version=API_VERSION,
    operations=OPERATIONS,
)

__all__ = (
    'CONTRACT_ID',
    'SERVICE',
    'API_VERSION',
    'OPERATION_IDS',
    'OPERATIONS',
    'CONTRACT',
    'MAX_PACKAGE_FILES',
    'MAX_PACKAGE_FILE_BYTES',
    'MAX_PACKAGE_TOTAL_BYTES',
    'ListBacktestRunSpecsRequestV1',
    'ListBacktestRunSpecsResponseV1',
    'ImportResearchPackageRequestV1',
    'ImportResearchPackageResponseV1',
)

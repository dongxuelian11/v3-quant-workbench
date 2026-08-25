from . import project_session
from . import data_source
from . import instrument
from . import data_snapshot
from . import universe
from . import research
from . import dataset
from . import strategy
from . import model
from . import study
from . import portfolio
from . import risk
from . import optimization
from . import backtest
from . import result
from . import task
from . import artifact
from . import product_entry

from types import MappingProxyType

_CONTRACTS = (
    project_session.CONTRACT,
    data_source.CONTRACT,
    instrument.CONTRACT,
    data_snapshot.CONTRACT,
    universe.CONTRACT,
    research.CONTRACT,
    dataset.CONTRACT,
    strategy.CONTRACT,
    model.CONTRACT,
    study.CONTRACT,
    portfolio.CONTRACT,
    risk.CONTRACT,
    optimization.CONTRACT,
    backtest.CONTRACT,
    result.CONTRACT,
    task.CONTRACT,
    artifact.CONTRACT,
    product_entry.CONTRACT,
)
SERVICE_CONTRACTS = MappingProxyType({item.service: item for item in _CONTRACTS})
OPERATIONS = MappingProxyType({
    operation.operation_id: operation
    for contract in _CONTRACTS
    for operation in contract.operations
})
SERVICE_COUNT = len(SERVICE_CONTRACTS)
OPERATION_COUNT = len(OPERATIONS)
# Bounded non-P0 Product Entry expansion (task-authorized): the original
# frozen v1 registry (17 services / 64 operations) remains an exact subset;
# Product Entry now owns three preserved 1.0 operations plus additive 1.1
# local-data/factor/Strategy preview/publish, Backtest preflight/command and
# project-home query.
if SERVICE_COUNT != 18 or OPERATION_COUNT != 74:
    raise RuntimeError(f'frozen registry mismatch: services={SERVICE_COUNT}, operations={OPERATION_COUNT}')

def get_operation(operation_id: str):
    return OPERATIONS[operation_id]

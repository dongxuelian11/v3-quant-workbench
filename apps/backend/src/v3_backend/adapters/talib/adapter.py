from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from v3_backend.domain.factors import BackendBinding, MissingSemantics, Series


TA_LIB_WRAPPER_VERSION = "0.7.1"
TA_LIB_LICENSE = "BSD-2-Clause"
TA_LIB_CORE_LICENSE = "BSD-3-Clause"


class TalibAdapterError(RuntimeError):
    pass


class TalibProvider(Protocol):
    wrapper_version: str
    core_version: str

    def sma(self, values: Sequence[float], timeperiod: int) -> Sequence[float]: ...


class ImportedTalibProvider:
    def __init__(self) -> None:
        try:
            import numpy
            import talib
        except ImportError as error:
            raise TalibAdapterError(
                "TA-Lib 0.7.1 direct dependency is unavailable"
            ) from error
        self._numpy = numpy
        self._talib = talib
        self.wrapper_version = str(talib.__version__)
        core = talib.__ta_version__
        self.core_version = (
            core.decode("ascii", "replace") if isinstance(core, bytes) else str(core)
        )

    def sma(self, values: Sequence[float], timeperiod: int) -> Sequence[float]:
        array = self._numpy.asarray(values, dtype=self._numpy.float64)
        return self._talib.SMA(array, timeperiod=timeperiod)


@dataclass(frozen=True, slots=True)
class TalibDependencyEvidence:
    wrapper_version: str
    core_version: str
    wrapper_license: str = TA_LIB_LICENSE
    core_license: str = TA_LIB_CORE_LICENSE
    authority: str = "NON_AUTHORITATIVE_COMPUTE_BACKEND"
    missing_contract: str = "INPUT_NONE_TO_NAN_AND_OUTPUT_NAN_TO_NONE_EXPLICITLY"


class TalibOperatorAdapter:
    backend_binding = BackendBinding.TA_LIB

    def __init__(self, provider: TalibProvider | None = None) -> None:
        self._provider = provider if provider is not None else ImportedTalibProvider()
        if self._provider.wrapper_version != TA_LIB_WRAPPER_VERSION:
            raise TalibAdapterError(
                f"TA-Lib wrapper must be exactly {TA_LIB_WRAPPER_VERSION}; "
                f"observed {self._provider.wrapper_version}"
            )

    @property
    def dependency_evidence(self) -> TalibDependencyEvidence:
        return TalibDependencyEvidence(
            wrapper_version=self._provider.wrapper_version,
            core_version=self._provider.core_version,
        )

    def execute(
        self,
        operator_name: str,
        inputs: tuple[Series, ...],
        parameters: Mapping[str, int],
        missing_semantics: MissingSemantics,
    ) -> Series:
        if operator_name != "SMA":
            raise TalibAdapterError(f"unsupported TA-Lib operator: {operator_name}")
        if missing_semantics is not MissingSemantics.PROPAGATE:
            raise TalibAdapterError("SMA adapter requires explicit PROPAGATE semantics")
        if len(inputs) != 1 or set(parameters) != {"timeperiod"}:
            raise TalibAdapterError("SMA adapter input/parameter contract mismatch")
        timeperiod = parameters["timeperiod"]
        encoded = tuple(math.nan if value is None else value for value in inputs[0])
        raw = tuple(self._provider.sma(encoded, timeperiod))
        if len(raw) != len(encoded):
            raise TalibAdapterError("TA-Lib changed output length")
        output: list[float | None] = []
        for index, value in enumerate(raw):
            normalized = float(value)
            if math.isnan(normalized):
                output.append(None)
            elif not math.isfinite(normalized):
                raise TalibAdapterError(
                    f"TA-Lib returned a non-finite non-NaN value at index {index}"
                )
            else:
                output.append(normalized)
        return tuple(output)


__all__ = [
    "ImportedTalibProvider",
    "TA_LIB_CORE_LICENSE",
    "TA_LIB_LICENSE",
    "TA_LIB_WRAPPER_VERSION",
    "TalibAdapterError",
    "TalibDependencyEvidence",
    "TalibOperatorAdapter",
    "TalibProvider",
]

"""Fail-closed errors for artifact and data-plane boundaries."""


class ArtifactError(RuntimeError):
    """Base class for artifact-domain failures."""


class InvalidArtifactIdentity(ArtifactError, ValueError):
    pass


class StagingNotFound(ArtifactError, FileNotFoundError):
    pass


class IntegrityMismatch(ArtifactError):
    pass


class ArtifactCollision(ArtifactError):
    pass


class DescriptorConflict(ArtifactError):
    pass


class FormatRejected(ArtifactError):
    pass


class ArtifactScanLimitExceeded(ArtifactError):
    """A bounded storage scan hit its hard safety ceiling."""


class CapabilityUnavailable(ArtifactError):
    def __init__(self, capability: str, reason: str) -> None:
        self.capability = capability
        self.reason = reason
        super().__init__(f"{capability} UNAVAILABLE: {reason}")


class GarbageCollectionSafetyError(ArtifactError):
    pass

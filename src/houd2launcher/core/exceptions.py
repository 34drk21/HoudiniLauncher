"""Domain exceptions used by HouD2Launcher."""


class HouD2Error(RuntimeError):
    """Base class for recoverable HouD2Launcher errors."""


class PathSafetyError(HouD2Error):
    """Raised when a requested path could escape its allowed root."""


class DuplicateRegistrationError(HouD2Error):
    """Raised when an object is already registered."""


class EnvironmentResolutionError(HouD2Error):
    """Raised when environment templates cannot be resolved safely."""


class HoudiniLaunchError(HouD2Error):
    """Raised when a Houdini process cannot be prepared or launched."""


class SettingsImportError(HouD2Error):
    """Raised when a settings package fails validation or import."""


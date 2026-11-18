"""Plain-language UI guidance with no Qt dependency."""
from __future__ import annotations

from dataclasses import dataclass

from backend import validate_name


@dataclass(frozen=True)
class CreationGuidance:
    can_configure: bool
    can_create: bool
    message: str
    state: str


def creation_guidance(kind: str, version: str, has_spec: bool, catalog_loading: bool,
                      creating: bool, accepted_eula: bool, name: str, folder: str) -> CreationGuidance:
    """Return button state and beginner-facing guidance for server creation."""
    can_configure = bool(has_spec) and not creating and not catalog_loading
    try:
        validate_name(str(name).strip())
        name_error = ""
    except ValueError as exc:
        name_error = str(exc)
    folder_ready = bool(str(folder).strip())
    can_create = can_configure and accepted_eula and not name_error and folder_ready

    if creating:
        message, state = "Creating your server… You can cancel the active download below.", "waiting"
    elif catalog_loading:
        message, state = "Loading compatible Minecraft versions…", "waiting"
    elif not has_spec:
        message, state = "Choose a compatible Minecraft version before continuing.", "waiting"
    elif name_error:
        message, state = "Server name: " + name_error, "warning"
    elif not folder_ready:
        message, state = "Choose where the new server folder should be created.", "warning"
    elif not accepted_eula:
        message, state = "One last step: read and accept the Minecraft EULA.", "warning"
    else:
        message = "Ready. Easy Realms will download the official server files and verify them where a checksum is available."
        state = "ready"

    return CreationGuidance(can_configure, can_create, message, state)

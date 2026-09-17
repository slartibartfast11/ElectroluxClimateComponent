from broadlink.exceptions import BroadlinkException, NetworkTimeoutError
from homeassistant.exceptions import HomeAssistantError


def device_command(command, *args):
    """Run a device command and translate expected transport errors for Home Assistant."""
    try:
        return command(*args)
    except (NetworkTimeoutError, OSError) as err:
        raise HomeAssistantError(
            f"Communication with Electrolux air conditioner failed: {err}"
        ) from err
    except BroadlinkException as err:
        raise HomeAssistantError(
            f"Electrolux air conditioner command failed: {err}"
        ) from err

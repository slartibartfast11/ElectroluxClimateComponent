from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ElectroluxCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    add_entities_async,
) -> None:
    """Set up the LED switch from the shared coordinator."""
    coordinator: ElectroluxCoordinator = entry.runtime_data
    add_entities_async([ElectroluxClimateLedEntity(coordinator, entry)])


class ElectroluxClimateLedEntity(
    CoordinatorEntity[ElectroluxCoordinator], SwitchEntity
):

    def __init__(
        self,
        coordinator: ElectroluxCoordinator,
        config: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.config = config

        self._attr_unique_id = coordinator.sn + "-led"
        self._attr_name = config.title + " LED"
        self._apply_coordinator_data()

    def _apply_coordinator_data(self) -> None:
        self._attr_is_on = self.coordinator.data["scrdisp"] == 1

    def _handle_coordinator_update(self) -> None:
        self._apply_coordinator_data()
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_execute(("set_led", (True,)))

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_execute(("set_led", (False,)))

    @property
    def device_info(self):
        return self.coordinator.device_info

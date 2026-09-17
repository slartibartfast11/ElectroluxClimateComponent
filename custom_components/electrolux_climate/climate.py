import typing as t

import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant.components.climate import ClimateEntity, PLATFORM_SCHEMA
from homeassistant.components.climate.const import (
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ClimateEntityFeature,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_OFF,
    HVACMode,
    SWING_OFF,
    SWING_VERTICAL,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_MAX, DEFAULT_MIN, FAN_QUIET, FAN_TURBO
from .coordinator import ElectroluxCoordinator
from .electrolux import electrolux

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(ATTR_MIN_TEMP, default=DEFAULT_MIN): cv.positive_int,
    vol.Optional(ATTR_MAX_TEMP, default=DEFAULT_MAX): cv.positive_int,
})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    add_entities_async,
) -> None:
    """Set up the climate entity from the shared coordinator."""
    coordinator: ElectroluxCoordinator = entry.runtime_data
    add_entities_async([ElectroluxClimateEntity(coordinator, entry)])


class ElectroluxClimateEntity(CoordinatorEntity[ElectroluxCoordinator], ClimateEntity):

    def __init__(
        self,
        coordinator: ElectroluxCoordinator,
        config: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.config = config

        self._attr_unique_id = coordinator.sn
        self._attr_name = config.title

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_precision = 1
        self._attr_target_temperature_step = 1
        self._attr_min_temp = config.data[ATTR_MIN_TEMP]
        self._attr_max_temp = config.data[ATTR_MAX_TEMP]
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.AUTO,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
            HVACMode.HEAT_COOL,
        ]
        self._attr_fan_mode = FAN_OFF
        self._attr_fan_modes = [
            FAN_AUTO,
            FAN_LOW,
            FAN_MEDIUM,
            FAN_HIGH,
            FAN_QUIET,
            FAN_TURBO,
        ]
        self._attr_swing_mode = SWING_OFF
        self._attr_swing_modes = [SWING_OFF, SWING_VERTICAL]
        self._attr_supported_features = (
            ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        self._apply_coordinator_data()

    def convert_to_hvacmode(self, state: int) -> str:
        match state:
            case electrolux.mode.AUTO.value:
                return HVACMode.AUTO
            case electrolux.mode.COOL.value:
                return HVACMode.COOL
            case electrolux.mode.HEAT.value:
                return HVACMode.HEAT
            case electrolux.mode.HEAT_8.value:
                return HVACMode.HEAT_COOL
            case electrolux.mode.DRY.value:
                return HVACMode.DRY
            case electrolux.mode.FAN.value:
                return HVACMode.FAN_ONLY
            case _:
                return HVACMode.AUTO

    def convert_to_fanmode(self, state: int) -> str:
        match state:
            case electrolux.fan.AUTO.value:
                return FAN_AUTO
            case electrolux.fan.LOW.value:
                return FAN_LOW
            case electrolux.fan.MID.value:
                return FAN_MEDIUM
            case electrolux.fan.HIGH.value:
                return FAN_HIGH
            case electrolux.fan.TURBO.value:
                return FAN_TURBO
            case electrolux.fan.QUIET.value:
                return FAN_QUIET
            case _:
                return FAN_AUTO

    def _apply_coordinator_data(self) -> None:
        state = self.coordinator.data
        self._attr_current_temperature = state["envtemp"]
        self._attr_target_temperature = state["temp"]
        self._attr_hvac_mode = (
            HVACMode.OFF
            if state["ac_pwr"] == 0
            else self.convert_to_hvacmode(state["ac_mode"])
        )
        self._attr_fan_mode = self.convert_to_fanmode(state["ac_mark"])
        self._attr_swing_mode = (
            SWING_OFF if state["ac_vdir"] == 0 else SWING_VERTICAL
        )

    def _handle_coordinator_update(self) -> None:
        self._apply_coordinator_data()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self.coordinator.async_execute(("set_power", (True,)))

    async def async_turn_off(self) -> None:
        await self.coordinator.async_execute(("set_power", (False,)))

    def convert_to_ele_mode(self, mode: HVACMode) -> electrolux.mode:
        match mode:
            case HVACMode.AUTO:
                return electrolux.mode.AUTO
            case HVACMode.HEAT:
                return electrolux.mode.HEAT
            case HVACMode.HEAT_COOL:
                return electrolux.mode.HEAT_8
            case HVACMode.COOL:
                return electrolux.mode.COOL
            case HVACMode.DRY:
                return electrolux.mode.DRY
            case HVACMode.FAN_ONLY:
                return electrolux.mode.FAN
            case _:
                return electrolux.mode.AUTO

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        commands: list[tuple[str, tuple[t.Any, ...]]] = []

        if hvac_mode == HVACMode.OFF and self.hvac_mode != HVACMode.OFF:
            commands.append(("set_power", (False,)))

        if hvac_mode != HVACMode.OFF:
            if self.hvac_mode == HVACMode.OFF:
                commands.append(("set_power", (True,)))
            commands.append(("set_mode", (self.convert_to_ele_mode(hvac_mode),)))

        if commands:
            await self.coordinator.async_execute(*commands)

    def convert_to_ele_fan(self, fan_mode: t.Literal) -> electrolux.fan:
        if fan_mode == FAN_AUTO:
            return electrolux.fan.AUTO
        if fan_mode == FAN_LOW:
            return electrolux.fan.LOW
        if fan_mode == FAN_MEDIUM:
            return electrolux.fan.MID
        if fan_mode == FAN_HIGH:
            return electrolux.fan.HIGH
        if fan_mode == FAN_TURBO:
            return electrolux.fan.TURBO
        if fan_mode == FAN_QUIET:
            return electrolux.fan.QUIET
        return electrolux.fan.AUTO

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self.coordinator.async_execute(
            ("set_fan", (self.convert_to_ele_fan(fan_mode),))
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self.coordinator.async_execute(
            ("set_swing", (swing_mode == SWING_VERTICAL,))
        )

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get("temperature")
        if isinstance(temperature, (int, float)):
            await self.coordinator.async_execute(("set_temp", (int(temperature),)))

    @property
    def device_info(self):
        return self.coordinator.device_info

"""Shared device runtime and state coordinator for Electrolux Climate."""

from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from time import monotonic
from typing import Any

import broadlink
from broadlink.exceptions import BroadlinkException, NetworkTimeoutError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL
from .device_command import device_command
from .electrolux import DEVICE_TYPE, electrolux

_LOGGER = logging.getLogger(__name__)

MAX_CONSECUTIVE_STATUS_FAILURES = 3


class ElectroluxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Own one authenticated Electrolux device and one shared status poll."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.host = (entry.data[CONF_HOST], broadlink.DEFAULT_PORT)
        self.mac = bytes.fromhex(entry.data[CONF_MAC])
        self.dev_name = entry.data[CONF_NAME]
        self.timeout = entry.data.get(CONF_TIMEOUT, broadlink.DEFAULT_TIMEOUT)

        self.device: electrolux | None = None
        self._device_lock = asyncio.Lock()
        self._identity_initialized = False
        self._validate_reported_sn = False
        self._has_valid_status = False
        self._consecutive_status_failures = 0

        self.sn = self.mac.hex()
        self.model: str | None = None
        self.manufacturer: str | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=SCAN_INTERVAL,
            update_method=self._async_update_data,
        )

    async def _async_setup(self) -> None:
        """Create and authenticate the shared device once."""
        if self.device is not None:
            return

        started = monotonic()
        try:
            self.device = await self.hass.async_add_executor_job(
                partial(
                    electrolux,
                    self.host,
                    self.mac,
                    DEVICE_TYPE,
                    self.timeout,
                    self.dev_name,
                    "",
                    "Electrolux",
                    False,
                )
            )
        except (NetworkTimeoutError, OSError, BroadlinkException) as err:
            raise UpdateFailed(
                f"Unable to connect to Electrolux air conditioner: {err}"
            ) from err

        _LOGGER.debug(
            "%s: device authenticated in %.2fs",
            self.entry.title,
            monotonic() - started,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch one status payload for all entities belonging to this AC."""
        if self.device is None:
            raise UpdateFailed("Electrolux device is not initialized")

        queued = monotonic()
        try:
            async with self._device_lock:
                waited = monotonic() - queued
                started = monotonic()
                raw_status = await self.hass.async_add_executor_job(
                    self.device.get_status
                )
        except (
            NetworkTimeoutError,
            OSError,
            BroadlinkException,
            UnicodeDecodeError,
        ) as err:
            return self._handle_status_failure(
                f"Unable to read Electrolux status: {err}", err
            )

        try:
            state = json.loads(raw_status)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as err:
            return self._handle_status_failure(
                f"Invalid Electrolux status response: {err}", err
            )

        if not isinstance(state, dict):
            return self._handle_status_failure(
                "Electrolux status response was not a JSON object"
            )

        _LOGGER.debug(
            "%s: status received in %.2fs after %.2fs waiting for device lock",
            self.entry.title,
            monotonic() - started,
            waited,
        )

        self._update_identity(state)
        self._handle_status_success()
        return state

    def _handle_status_failure(
        self, message: str, err: BaseException | None = None
    ) -> dict[str, Any]:
        """Retain last-known state for brief status failures after initial setup."""
        self._consecutive_status_failures += 1
        failures = self._consecutive_status_failures

        if not self._has_valid_status:
            if err is not None:
                raise UpdateFailed(message) from err
            raise UpdateFailed(message)

        if failures >= MAX_CONSECUTIVE_STATUS_FAILURES:
            _LOGGER.warning(
                "%s: status read failed %d consecutive times; marking unavailable: %s",
                self.entry.title,
                failures,
                message,
            )
            if err is not None:
                raise UpdateFailed(message) from err
            raise UpdateFailed(message)

        _LOGGER.warning(
            "%s: status read failed (%d/%d); retaining last known state: %s",
            self.entry.title,
            failures,
            MAX_CONSECUTIVE_STATUS_FAILURES,
            message,
        )
        return self.data

    def _handle_status_success(self) -> None:
        """Reset transient polling failure state after a valid status response."""
        if self._consecutive_status_failures:
            _LOGGER.info(
                "%s: status recovered after %d consecutive failure%s",
                self.entry.title,
                self._consecutive_status_failures,
                "" if self._consecutive_status_failures == 1 else "s",
            )

        self._consecutive_status_failures = 0
        self._has_valid_status = True

    def _update_identity(self, state: dict[str, Any]) -> None:
        """Capture stable device metadata from the first successful status."""
        reported_sn = state.get("sn")

        if not self._identity_initialized:
            if reported_sn:
                self.sn = str(reported_sn)
                self._validate_reported_sn = True
            else:
                self.sn = self.mac.hex()
                _LOGGER.warning(
                    "SN not available for %s; using MAC address as device identifier",
                    self.entry.title,
                )

            self.model = state.get("modelnumber")
            if self.model and self.model.upper().startswith("KSV"):
                self.manufacturer = "Kelvinator"

            self._identity_initialized = True
            return

        if (
            self._validate_reported_sn
            and reported_sn
            and str(reported_sn) != self.sn
        ):
            raise UpdateFailed(
                f"Electrolux status serial number changed from {self.sn} to {reported_sn}"
            )

        if self.model is None and state.get("modelnumber"):
            self.model = state["modelnumber"]
            if self.model.upper().startswith("KSV"):
                self.manufacturer = "Kelvinator"

    async def async_execute(
        self, *commands: tuple[str, tuple[Any, ...]]
    ) -> None:
        """Run one logical HA operation as serialized device commands."""
        if self.device is None:
            raise UpdateFailed("Electrolux device is not initialized")

        labels = ", ".join(command for command, _ in commands)
        queued = monotonic()

        try:
            async with self._device_lock:
                waited = monotonic() - queued
                started = monotonic()
                for command_name, args in commands:
                    command = getattr(self.device, command_name)
                    await self.hass.async_add_executor_job(
                        partial(device_command, command, *args)
                    )
        except Exception:
            _LOGGER.debug(
                "%s: command sequence [%s] failed after %.2fs",
                self.entry.title,
                labels,
                monotonic() - queued,
                exc_info=True,
            )
            raise

        _LOGGER.debug(
            "%s: command sequence [%s] completed in %.2fs after %.2fs waiting for device lock",
            self.entry.title,
            labels,
            monotonic() - started,
            waited,
        )

        # Refresh immediately once per logical operation so HA reflects what the
        # hardware actually reports, rather than having each entity poll itself.
        await self.async_refresh()

    @property
    def device_info(self) -> dr.DeviceInfo:
        """Return shared physical-device information."""
        info = dr.DeviceInfo(
            connections={(dr.CONNECTION_NETWORK_MAC, self.mac.hex())},
            identifiers={(DOMAIN, self.sn)},
            name=self.entry.title,
        )
        if self.model:
            info["model"] = self.model
        if self.manufacturer:
            info["manufacturer"] = self.manufacturer
        return info

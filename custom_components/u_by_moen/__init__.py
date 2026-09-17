"""The U by Moen integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MoenApi, MoenAuthError
from .const import DOMAIN
from .coordinator import MoenDataUpdateCoordinator
from .pusher import MoenPusherTransport

PLATFORMS = [Platform.CLIMATE, Platform.SWITCH, Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up U by Moen from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    session = async_get_clientsession(hass)
    api = MoenApi(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], session)
    try:
        await api.authenticate()
    except MoenAuthError as err:
        raise ConfigEntryAuthFailed from err

    pusher = MoenPusherTransport(
        api,
        session,
        create_task=lambda coroutine: hass.async_create_task(
            coroutine, "U by Moen Pusher supervisor"
        ),
    )
    coordinator = MoenDataUpdateCoordinator(hass, api, pusher)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "pusher": pusher,
    }
    await coordinator.async_start_pusher()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and its supervised transport."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["pusher"].stop()
    return unload_ok

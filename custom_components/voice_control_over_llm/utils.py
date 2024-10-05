import logging
from typing import Any, Callable
from homeassistant.core import HomeAssistant
from .const import DOMAIN

LOGGER = logging.getLogger(DOMAIN)

def print(msg: str) -> Callable[[str], None]:
    return LOGGER.info(msg)

class HomeAssistantStub:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_add_executor_job(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        return await self.hass.async_add_executor_job(func, *args, **kwargs)

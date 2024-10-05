from typing import Any, Dict, Optional
from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol
from .const import DOMAIN, CONF_HA_API_TOKEN, CONF_GEMINI_API_TOKEN, CONF_HA_URL

class MyConversationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Voice Control integration."""
    
    VERSION = 1

    async def async_step_user(self, 
                              user_input: Optional[Dict[str, Any]] = None,
                              ) -> config_entries.FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(title="Conversation API", data=user_input)

        return self._show_config_form()

    @callback
    def _show_config_form(self, 
                          user_input: Optional[Dict[str, Any]] = None,
                          ) -> config_entries.FlowResult:
        """Show the configuration form to edit location data."""
        schema = vol.Schema({
            vol.Required(CONF_HA_API_TOKEN): str,
            vol.Required(CONF_GEMINI_API_TOKEN): str,
            vol.Optional(CONF_HA_URL, 
                         description={"suggested_value": "http://homeassistant.local:8123"}, 
                         default="http://homeassistant.local:8123"): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_import(self, 
                                user_input: Optional[Dict[str, Any]] = None,
                                ) -> config_entries.FlowResult:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(user_input)
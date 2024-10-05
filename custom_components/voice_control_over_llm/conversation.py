from homeassistant.components import assist_pipeline, conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import ulid
from homeassistant.helpers import device_registry as dr
from typing import Any, Literal, Tuple, Dict, List, Union

from .langchainMgr import LangchainMgr, OpRunner

from .const import (
    DOMAIN
)
from .utils import LOGGER, HomeAssistantStub
from . import const

def get_ha_info(entry: ConfigEntry) -> Tuple[str, Dict[str, str]]:
    """
    Retrieve Home Assistant URL and headers from the config entry.

    Args:
        entry (ConfigEntry): The configuration entry.

    Returns:
        Tuple[str, Dict[str, str]]: The Home Assistant URL and headers.
    """
    dns = entry.options.get(const.CONF_HA_URL, "http://homeassistant.local:8123")
    ha_token = entry.data.get(const.CONF_HA_API_TOKEN, "")
    headers = {
        "Authorization": "Bearer " + ha_token,
        "Content-Type": "application/json"
    }
    return dns, headers

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up conversation entities.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        config_entry (ConfigEntry): The configuration entry.
        async_add_entities (AddEntitiesCallback): Callback to add entities.
    """
    LOGGER.info("Setting up conversation entities")
    url, headers = get_ha_info(config_entry)
    chain = LangchainMgr(config_entry.data.get(const.CONF_GEMINI_API_TOKEN, ""),
                         HomeAssistantStub(hass), url, headers)
    agent = ConversationEntity(hass, config_entry, chain)
    async_add_entities([agent])

class ConversationEntity(
    conversation.ConversationEntity, conversation.AbstractConversationAgent
):
    """Conversation agent powered by Google Generative AI."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, chain: LangchainMgr) -> None:
        """
        Initialize the agent.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            entry (ConfigEntry): The configuration entry.
            chain (LangchainMgr): The Langchain manager instance.
        """
        LOGGER.info("Initializing Agent")
        self.entry = entry
        self.hass = hass
        self.history: Dict[str, conversation.ConversationInput] = {}
        self.url, self.headers = get_ha_info(entry)

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Kaijia",
            model="Generative AI",
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        self.chain = chain
        self.runner = OpRunner(self.headers, self.url, self.hass)
        self._attr_supported_features = (
            conversation.ConversationEntityFeature.CONTROL
        )

    @property
    def supported_languages(self) -> Union[List[str], Literal["*"]]:
        """
        Return a list of supported languages.

        Returns:
            Union[List[str], Literal["*"]]: Supported languages.
        """
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        assist_pipeline.async_migrate_engine(
            self.hass, "conversation", self.entry.entry_id, self.entity_id
        )
        conversation.async_set_agent(self.hass, self.entry, self)
        self.entry.async_on_unload(
            self.entry.add_update_listener(self._async_entry_update_listener)
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """
        Process a sentence.

        Args:
            user_input (conversation.ConversationInput): The user input.

        Returns:
            conversation.ConversationResult: The result of the conversation.
        """
        LOGGER.info("Processing user input with text: %s" % user_input.text)
        resp = "Something went wrong"
        await self.chain.update()
        try:
            resp = self.chain.invoke(user_input.text)
            LOGGER.info("Response from langchain: %s" % resp)
        except Exception:
            LOGGER.exception("Error invoking langchain")
        result = conversation.ConversationResult(
            response=intent.IntentResponse(language=user_input.language),
            conversation_id=user_input.conversation_id
            if user_input.conversation_id in self.history
            else ulid.ulid_now(),
        )
        self.history[result.conversation_id] = user_input
        resp_txt = await self.runner.runOps(resp)
        result.response.async_set_speech(
            resp_txt
        )
        return result

    async def _async_entry_update_listener(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """
        Handle options update.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            entry (ConfigEntry): The configuration entry.
        """
        # Reload as we update device info + entity name + supported features
        await hass.config_entries.async_reload(entry.entry_id)
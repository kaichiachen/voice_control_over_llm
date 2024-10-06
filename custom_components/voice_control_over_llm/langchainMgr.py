from langchain_google_genai import ChatGoogleGenerativeAI
from google.generativeai.types.safety_types import HarmBlockThreshold, HarmCategory
from langchain_core.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from .utils import print, HomeAssistantStub

import json
import requests

class Entity(BaseModel):
    entity_id: str = Field(description="entity id of device. Only match if high confident with device name")
    state: str = Field(description="state of entity")

class Switch(Entity):
    action: str = Field(description="action for the device from {user_input}. Only can be on/off/other. Default value is other")

class Fan(Switch):
    percentage: float = Field(description="the percentage or number represent the level of fan air volume from {user_input}. Set value as -1 if no mention from {user_input}")

class Climate(Switch):
    temperature: float = Field(description="the temperature represent air condition's target temperature from {user_input}. Set value as -1 if no mention from {user_input}")
    fan_mode: str = Field(description="fan mode of air condition. Only can be auto/low/medium/high/other Default value is other")
    hvac_mode: str = Field(description="HVAC(Heating, Ventilation, and Air Conditioning) of air condition. Only can be heat_cool/cool/dry/fan_only/heat/other Default value is other")

class HomeAssistant(BaseModel):
    switch: List[Switch]
    fan: List[Fan]
    climate: List[Climate]
    response: str = Field(description="Response text accroding to {user_input} with maximum 100 words and minium 2 words. Answer in plain text. Keep it simple to the point. Please do not include any text formatting and reply with language of {user_input}. If language is chinese, should identify traditional chinese or simple chinese and traditional chinese first if unidentifiable")

class LangchainMgr:

     def __init__(self, api_key: str,
                  hass: HomeAssistantStub, url: str,
                  headers: Dict[str, str]) -> None:
        self.api_key = api_key
        self.hass = hass
        self.url = url
        self.headers = headers
        self.parser = PydanticOutputParser(pydantic_object=HomeAssistant)
        self.llm = None
        self.chain= None

     def invoke(self, user_input: str) -> Any:
        if self.chain is None:
            raise Exception("Chain is not initialized")
        response = self.chain.invoke({"user_input": user_input})
        return response

     def getLLM(self) -> ChatGoogleGenerativeAI:
          safety_settings = {
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
          }
          return ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest",
                                                safety_settings=safety_settings,
                                                google_api_key=self.api_key)

     async def update(self) -> None:
          print("Updating chain")
          entity_map = await async_get_devices_info(self.hass, self.url, self.headers)

          prompt = PromptTemplate(
             template = """
             You are the voice assistant for Home Assistant but be able to response other common questions.
             An overview of the areas and the devices in this smart home with entity_map format (entity name: entity_id) :\n {entity_map} \n\n\n
             Extract the following information {format_instructions} from the input text: "{user_input} and entity_map"
             """,
             input_variables = ['user_input'],
             partial_variables={
                 "format_instructions": self.parser.get_format_instructions(),
                 "entity_map": json.dumps(entity_map)},
          )

          if self.llm is None:
              self.llm = await self.hass.async_add_executor_job(self.getLLM)

          self.chain = prompt | self.llm  | self.parser
          print("Chain is updated")


class OpRunner:

    def __init__(self, headers: Dict[str, str], url: str, hass: HomeAssistantStub) -> None:
        self.headers = headers
        self.url = url
        self.hass = hass

    def postCmd(self, endpoint: str, data: Dict[str, Any]) -> None:
        requests.post(endpoint, headers=self.headers, data=json.dumps(data))

    async def switchAction(self, entity_id: str, action: str) -> None:
        data = {'entity_id': entity_id}
        endpoint = ''
        typ = entity_id.split('.')[0]
        if action == 'on':
            endpoint = self.url+'/api/services/'+ typ +'/turn_on'
        elif action == 'off':
            endpoint = self.url+'/api/services/' + typ + '/turn_off'

        if endpoint:
            await self.hass.async_add_executor_job(self.postCmd, endpoint, data)

    async def setPercentage(self, entity_id: str, device: str, percentage: float) -> None:
        data = {'entity_id': entity_id, 'percentage': min(percentage, 100)}
        endpoint = self.url+'/api/services/'+device+'/set_percentage'
        await self.hass.async_add_executor_job(self.postCmd, endpoint, data)

    async def setHVAC(self, entity_id: str, hvac_mode: str) -> None:
        if hvac_mode not in ('heat_cool', 'cool', 'dry', 'fan_only', 'heat'):
            return
        data = {'entity_id': entity_id, 'hvac_mode': hvac_mode}
        endpoint = self.url+'/api/services/climate/set_hvac_mode'
        await self.hass.async_add_executor_job(self.postCmd, endpoint, data)


    async def setFan(self, entity_id: str, fan_mode: str) -> None:
        if fan_mode not in ('auto', 'low', 'medium', 'high'):
            return
        data = {'entity_id': entity_id, 'fan_mode': fan_mode}
        endpoint = self.url+'/api/services/climate/set_fan_mode'
        await self.hass.async_add_executor_job(self.postCmd, endpoint, data)


    async def setTemperature(self, entity_id: str, temperature: float) -> None:
        data = {'entity_id': entity_id, 'temperature': min(temperature, 100)}
        endpoint = self.url+'/api/services/climate/set_temperature'
        await self.hass.async_add_executor_job(self.postCmd, endpoint, data)


    async def runOps(self, op: HomeAssistant) -> str:
        switchs = op.switch
        for switch in switchs:
            if switch.state != switch.action:
                await self.switchAction(switch.entity_id, switch.action)

        fans = op.fan
        for fan in fans:
            if fan.state != fan.action:
                await self.switchAction(fan.entity_id, fan.action)
            if fan.percentage >= 0 and fan.action != 'other':
                await self.setPercentage(fan.entity_id, 'fan', fan.percentage)

        climates = op.climate
        for climate in climates:
            if climate.state != climate.action:
                await self.switchAction(climate.entity_id, climate.action)
            if climate.action != 'other':
                await self.setHVAC(climate.entity_id, climate.hvac_mode)
                await self.setFan(climate.entity_id, climate.fan_mode)
                await self.setTemperature(climate.entity_id, climate.temperature)

        resp = op.response
        return resp


async def async_get_devices_info(
          hass: HomeAssistantStub,
          dns: str,
          headers: Dict[str, str]) -> List[Dict[str, Any]]:

     def query_device_info() -> requests.Response:
          url = f"{dns}/api/states"
          response = requests.get(url, headers=headers)
          return response

     resp = await hass.async_add_executor_job(query_device_info)

     states: List[Dict[str, Any]] = []

     def handle_entity(entity: Dict[str, Any]) -> None:
          states.append(entity)

     support_entities = {
          "light": handle_entity,
          "switch": handle_entity,
          "fan": handle_entity,
          "vacuum": handle_entity,
          "input_boolean": handle_entity,
          "sensor": handle_entity,
          "climate": handle_entity,
     }

     try:
          for item in resp.json():
                k = item['entity_id']
                for key in support_entities.keys():
                     if k.startswith(key):
                          support_entities[key](item)
                          break
     except Exception as e:
          print(resp.text)
          print("Error: ", e)

     return states

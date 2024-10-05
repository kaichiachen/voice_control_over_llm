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
    action: str = Field(description="action for the device. Only can be on/off/other. Default value is other")

class Fan(Switch):
    percentage: float = Field(description="the percentage or number represent the level of air volume that user to set. Only for fan. Default value is -1 if no mention")

class HomeAssistant(BaseModel):
    switch: List[Switch]
    fan: List[Fan]
    response: str = Field(description="Response text accroding to {user_input} with maximum 100 words and minium 2 words. Answer in plain text. Keep it simple to the point. Please do not include any text formatting and reply with traditional chinese")

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
             You are the voice assistant for Home Assistant.
             An overview of the areas and the devices in this smart home with format (entity name: entity_id) :\n {entity_map} \n
             Extract the following information {format_instructions} from the input text: "{user_input}"
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

    def __init__(self, headers: Dict[str, str], url: str, hass: HomeAssistant) -> None:
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

    async def runOps(self, op: HomeAssistant) -> str:
        switchs = op.switch
        fans = op.fan
        for fan in fans:
            if fan.state != fan.action:
                await self.switchAction(fan.entity_id, fan.action)
            if fan.percentage >= 0:
                await self.setPercentage(fan.entity_id, 'fan', fan.percentage)

        resp = op.response
        return resp


async def async_get_devices_info(
          hass: HomeAssistant, 
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
          "sensor": handle_entity
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
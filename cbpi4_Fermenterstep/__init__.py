
import asyncio

from cbpi.api import parameters, Property, action
from cbpi.api.step import StepResult, CBPiFermentationStep
from cbpi.api.timer import Timer
from datetime import datetime
import time
from voluptuous.schema_builder import message
from cbpi.api.dataclasses import NotificationAction, NotificationType
from cbpi.api.dataclasses import Kettle, Props, Fermenter
from cbpi.api import *
import logging
from socket import timeout
from typing import KeysView
from cbpi.api.config import ConfigType
from cbpi.api.base import CBPiBase
import numpy as np
import warnings

logger = logging.getLogger(__name__)


@parameters([Property.Number(label="Temp", configurable=True, description = "Ramp to this temp"),
             Property.Number(label="RampRate", configurable=True, description = "Ramp x °C/F per  day. Default: 1"),
             Property.Sensor(label="Sensor"),
             Property.Text(label="Notification",configurable = True, description = "Text for notification when Temp is reached"),
             Property.Select(label="AutoMode",options=["Yes","No"], description="Switch Fermenterlogic automatically on and off -> Yes")])
class FermenterRampTempStep(CBPiFermentationStep):

    async def NextStep(self, **kwargs):
        if self.shutdown != True:
            await self.next(self.fermenter.id)
            return StepResult.DONE
        
    async def on_timer_done(self,timer):
        self.summary = ""
        await self.push_update()
        if self.AutoMode == True:
            await self.setAutoMode(False)
        self.cbpi.notify(self.name, self.props.get("Notification","Target Temp reached. Please add malt and klick next to move on."))
        await self.next(self.fermenter.id)
        return StepResult.DONE
        

    async def on_timer_update(self,timer, seconds):
        await self.push_update()

    async def on_start(self):
        self.shutdown = False
        self.AutoMode = True if self.props.get("AutoMode","No") == "Yes" else False
        self.rate=float(self.props.get("RampRate",1))
        logging.info(self.rate)
        self.target_temp = round(float(self.props.get("Temp", 0))*10)/10
        logging.info(self.target_temp)
        while self.get_sensor_value(self.props.get("Sensor", None)).get("value") > 900:
            await asyncio.sleep(1)
        self.starttemp = self.get_sensor_value(self.props.get("Sensor", None)).get("value")

        self.current_target_temp = self.starttemp
        if self.fermenter is not None:
            await self.set_fermenter_target_temp(self.fermenter.id, self.current_target_temp)
        if self.AutoMode == True:
            await self.setAutoMode(True)
        self.summary = "Ramping to {}° with {}° per day".format(self.target_temp,self.rate)
        if self.fermenter is not None and self.timer is None:
            self.timer = Timer(1 ,on_update=self.on_timer_update, on_done=self.on_timer_done)
        await self.push_update()

    async def on_stop(self):
        await self.timer.stop()
        self.summary = ""
        if self.AutoMode == True:
            await self.setAutoMode(False)
        await self.push_update()

    async def calc_target_temp(self):
        delta_time = time.time() - self.starttime
        current_target_temp = round((self.starttemp + delta_time * self.ratesecond)*10)/10
#        logging.info(current_target_temp)
        if current_target_temp != self.current_target_temp:
            self.current_target_temp = current_target_temp
            await self.set_fermenter_target_temp(self.fermenter.id, self.current_target_temp)
            #self.fermenter.target_temp = self.current_target_temp
            await self.push_update()

        pass

    async def run(self): 
        self.delta_temp = self.target_temp-self.starttemp
        try:
            self.deltadays = self.delta_temp / self.rate
            self.deltaseconds = self.deltadays * 24 * 60 * 60
            self.ratesecond = self.delta_temp/self.deltaseconds
        except Exception as e:
            logging.info(e)
        self.starttime=time.time()
        
        if self.target_temp >= self.starttemp:
            logging.info("warmup")
            while self.running == True:
                await self.calc_target_temp()
                sensor_value = self.get_sensor_value(self.props.get("Sensor", None)).get("value")
                if sensor_value >= self.target_temp and self.timer.is_running is not True:
                    self.timer.start()
                    self.timer.is_running = True
                await asyncio.sleep(1)
        elif self.target_temp <= self.starttemp:
            logging.info("Cooldown")
            while self.running == True:
                await self.calc_target_temp()
                sensor_value = self.get_sensor_value(self.props.get("Sensor", None)).get("value")
                if sensor_value <= self.target_temp and self.timer.is_running is not True:
                    self.timer.start()
                    self.timer.is_running = True
                await asyncio.sleep(1)
        await self.push_update()
        return StepResult.DONE

    async def reset(self):
        self.timer = Timer(1 ,on_update=self.on_timer_update, on_done=self.on_timer_done)
        self.timer.is_running == False

    async def setAutoMode(self, auto_state):
        try:
            if (self.fermenter.instance is None or self.fermenter.instance.state == False) and (auto_state is True):
                await self.cbpi.fermenter.toggle(self.fermenter.id)
            elif (self.fermenter.instance.state == True) and (auto_state is False):
                await self.fermenter.instance.stop()
            await self.push_update()

        except Exception as e:
            logging.error("Failed to switch on FermenterLogic {} {}".format(self.fermenter.id, e))

def setup(cbpi):
    cbpi.plugin.register("FermenterRampTempStep", FermenterRampTempStep)
    pass

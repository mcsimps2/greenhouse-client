import datetime
import time
import traceback

import RPi.GPIO as gpio
import bme280
import requests
import smbus2

"""
IN1 - 11 GPIO17 (Fan, D8)
IN2 - 12 GPIO18 (Big greenhouse light, D7)
IN3 - 13 GPIO27 (D6)
IN4 - 15 GPIO22 (D5)
IN5 - 16 GPIO23 (D4)
IN6 - 18 GPIO24 (Small greenhouse light, D3)
IN7 - 22 GPIO25 (Lowe's Light, D2)
IN8 - 7 GPIO4 (Humidifier, D1)
VCC - Pin 2 (5V)
GND to Pin 14 (GND)
"""

BME_PORT = 1
BME_ADDRESS = 0x77
HUMIDIFIER_CHANNEL = 4
FAN_CHANNEL = 17
TOP_LIGHT_CHANNEL = (25, 18, 24)
INTERVAL = 15
LOWER_THRESHOLD = 75
UPPER_THRESHOLD = 85
GRACE_HUMIDITY = 3
TOP_LIGHT_ON = datetime.time(hour=9, minute=30)
TOP_LIGHT_OFF = datetime.time(hour=19)
SERIAL = "0000000011dd6dee"
API_URL = "http://localhost:80"
BME280_REGISTER_SOFTRESET = 0xE0


def do_try(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except:
        traceback.print_exc()


def reset_sensor(self):
    self._device.write8(BME280_REGISTER_SOFTRESET, 0xB6)
    return


def record_sample(humidity, temperature, humidifier_state, fan_state, lights_state):
    response = requests.post(f"{API_URL}/greenhouse/{SERIAL}/sample", headers={"Content-Type": "application/json"}, json={
        "humidity": humidity,
        "temperature": temperature,
        "humidifier_state": humidifier_state,
        "fan_state": fan_state,
        "lights_state": lights_state
    })
    response.raise_for_status()
    return response


class Greenhouse:
    def __init__(self, bme_port, bme_address, humidifier_channel, fan_channel, top_light_channel, top_light_on, top_light_off):
        self.bme_port = bme_port
        self.bme_bus = smbus2.SMBus(bme_port)
        self.bme_address = bme_address
        self.humidifier_channel = humidifier_channel
        self.fan_channel = fan_channel
        self.top_light_channel = top_light_channel
        self.humidifier_state = 1
        self.fan_state = 1
        self.top_light_state = 1
        self.top_light_on = top_light_on
        self.top_light_off = top_light_off

    def initialize_devices(self):
        time.sleep(1)
        bme280.load_calibration_params(self.bme_bus, self.bme_address)

        gpio.setmode(gpio.BCM)
        gpio.setup(self.humidifier_channel, gpio.OUT)
        gpio.setup(self.fan_channel, gpio.OUT)
        gpio.setup(self.top_light_channel, gpio.OUT)
        self.set_humidifier_state(1)
        self.set_fan_state(1)
        self.set_top_light_state(1)

    def set_top_light_state(self, state):
        self.top_light_state = state
        for channel in self.top_light_channel:
            gpio.output(channel, state)

    def set_humidifier_state(self, state):
        self.humidifier_state = state
        gpio.output(self.humidifier_channel, state)

    def set_fan_state(self, state):
        self.fan_state = state
        gpio.output(self.fan_channel, state)

    def toggle_top_light(self):
        if self.top_light_state:
            self.set_top_light_state(0)

    def disable_top_light(self):
        if not self.top_light_state:
            self.set_top_light_state(1)

    def toggle_humidifier(self):
        if self.humidifier_state:
            self.set_humidifier_state(0)

    def disable_humidifier(self):
        if not self.humidifier_state:
            self.set_humidifier_state(1)

    def toggle_fan(self):
        if self.fan_state:
            self.set_fan_state(0)

    def disable_fan(self):
        if not self.fan_state:
            self.set_fan_state(1)

    def sample(self):
        bme280_data = bme280.sample(self.bme_bus, self.bme_address)
        temperature = bme280_data.temperature * (9/5.0) + 32
        humidity = bme280_data.humidity
        return temperature, humidity

    def monitor(self, interval, lower, upper):
        temp, hum = self.sample()
        print("Temperature: {:.1f} F \tHumidity: {:.1f}% \tState: {}{}".format(temp, hum, self.humidifier_state, self.fan_state))
        if self.humidifier_state == 0 and hum < lower + GRACE_HUMIDITY:
            self.toggle_humidifier()
            self.toggle_fan()
        elif self.humidifier_state == 1 and hum < lower:
            self.toggle_humidifier()
            self.toggle_fan()
        elif self.fan_state == 0 and hum > upper - GRACE_HUMIDITY:
            self.disable_humidifier()
            self.toggle_fan()
        elif self.fan_state == 1 and hum > upper:
            self.disable_humidifier()
            self.toggle_fan()
        else:
            self.disable_humidifier()
            self.disable_fan()
        """
        if hum < lower:
            self.toggle_humidifier()
            self.toggle_fan()
        elif hum > upper:
            self.disable_humidifier()
            self.toggle_fan()
        else:
            self.disable_humidifier()
            self.disable_fan()
        """
        now = datetime.datetime.now().time()
        # now = datetime.datetime(year=2020, month=1, day=1, hour=8).time()
        if self.top_light_on <= now <= self.top_light_off:
            self.toggle_top_light()
        else:
            self.disable_top_light()

        record_sample(hum, temp, self.humidifier_state, self.fan_state, self.top_light_state)
        time.sleep(interval)

    def run(self, interval, lower, upper):
        while True:
            try:
                self.monitor(interval, lower, upper)
            except:
                traceback.print_exc()
                print("Failsafe activated")
                print("Disabling humidifier")
                do_try(self.disable_humidifier)
                print("Disabling fan")
                do_try(self.disable_fan)
                print("Disabling lights")
                do_try(self.disable_top_light)
                time.sleep(5)


def main():
    controller = Greenhouse(BME_PORT, BME_ADDRESS, HUMIDIFIER_CHANNEL, FAN_CHANNEL, TOP_LIGHT_CHANNEL, TOP_LIGHT_ON, TOP_LIGHT_OFF)
    controller.initialize_devices()
    controller.run(INTERVAL, LOWER_THRESHOLD, UPPER_THRESHOLD)


if __name__ == "__main__":
    try:
        main()
    finally:
        print("Cleaning up")
        gpio.cleanup()


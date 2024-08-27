# -*- coding: utf-8 -*-
"""Test using the InfluxDB client."""

import time
import colorsys
import os
import sys
import socket
import ST7735
import ltr559

from bme280 import BME280
from enviroplus import gas
from subprocess import PIPE, Popen
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from influxdb import InfluxDBClient

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

print("""

Press Ctrl+C to exit!

""")

# BME280 temperature/pressure/humidity sensor
bus = SMBus(1)
bme280 = BME280(i2c_dev=bus)

# Create ST7735 LCD display class
st7735 = ST7735.ST7735(
    port=0,
    cs=1,
    dc=9,
    backlight=12,
    rotation=270,
    spi_speed_hz=10000000
)

# Initialize display
st7735.begin()

WIDTH = st7735.width
HEIGHT = st7735.height

# Set up canvas and font
img = Image.new('RGB', (WIDTH, HEIGHT), color=(0, 0, 0))
draw = ImageDraw.Draw(img)
path = os.path.dirname(os.path.realpath(__file__))
font = ImageFont.truetype(path + "/fonts/Asap/Asap-Bold.ttf", 20)

# Set up InfluxDB
influx = InfluxDBClient(host="influx.domain.tld",
                        username="username",
                        password="secret",
                        database="enviroplus")

influx_json_prototyp = [
        {
            "measurement": "enviroplus",
            "tags": {
                "host": "enviroplus"
            },
            "fields": {
            }
        }
    ]

# The position of the top bar
top_pos = 25


# Displays data and text on the 0.96" LCD
def display_text(variable, data, unit):
    # Maintain length of list
    values[variable] = values[variable][1:] + [data]
    # Scale the values for the variable between 0 and 1
    colours = [(v - min(values[variable]) + 1) / (max(values[variable])
               - min(values[variable]) + 1) for v in values[variable]]
    # Format the variable name and value
    message = "{}: {:.1f} {}".format(variable[:4], data, unit)
    print(message)
    draw.rectangle((0, 0, WIDTH, HEIGHT), (255, 255, 255))
    for i in range(len(colours)):
        # Convert the values to colours from red to blue
        colour = (1.0 - colours[i]) * 0.6
        r, g, b = [int(x * 255.0) for x in colorsys.hsv_to_rgb(colour,
                   1.0, 1.0)]
        # Draw a 1-pixel wide rectangle of colour
        draw.rectangle((i, top_pos, i+1, HEIGHT), (r, g, b))
        # Draw a line graph in black
        line_y = HEIGHT - (top_pos + (colours[i] * (HEIGHT - top_pos)))\
                 + top_pos
        draw.rectangle((i, line_y, i+1, line_y+1), (0, 0, 0))
    # Write the text at the top in black
    draw.text((0, 0), message, font=font, fill=(0, 0, 0))
    st7735.display(img)


# Get the temperature of the CPU for compensation
def get_cpu_temperature():
    process = Popen(['vcgencmd', 'measure_temp'], stdout=PIPE)
    output, _error = process.communicate()
    output = output.decode()
    return float(output[output.index('=') + 1:output.rindex("'")])

# Get local IP address
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# Tuning factor for compensation. Decrease this number to adjust the
# temperature down, and increase to adjust up
factor = 0.8

cpu_temps = [0] * 5

delay = 0.5  # Debounce the proximity tap
mode = 0  # The starting mode
last_page = 0
light = 1

font_size = 25
text_colour = (128, 128, 128)
back_colour = (0, 0, 0)

size_x, size_y = draw.textsize(get_ip(), font)

# Calculate text position
x = (WIDTH - size_x) / 2
y = (HEIGHT / 2) - (size_y / 2)

# Draw background rectangle and write text.
draw.rectangle((0, 0, 160, 80), back_colour)
draw.text((x, y), get_ip(), font=font, fill=text_colour)
st7735.display(img)

# Create a values dict to store the data
variables = ["temperature",
             "pressure",
             "humidity",
             "light",
             "oxidised",
             "reduced",
             "nh3"]

values = {}

for v in variables:
    values[v] = [1] * WIDTH

# The main loop
try:
    iterations = 0
    while True:
        proximity = ltr559.get_proximity()

        # Compensated Temperature
        cpu_temp = get_cpu_temperature()
        # Smooth out with some averaging to decrease jitter
        cpu_temps = cpu_temps[1:] + [cpu_temp]
        avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
        raw_temp = bme280.get_temperature()
        compensated_temp = raw_temp - ((avg_cpu_temp - raw_temp) / factor)

        # Change json
        influx_json_prototyp[0]['fields']['ltr559.proximity'] = proximity

        if proximity < 10:
            influx_json_prototyp[0]['fields']['ltr559.lux'] = ltr559.get_lux()
        else:
            influx_json_prototyp[0]['fields']['ltr559.lux'] = 1.0

        if iterations >= 6:
            influx_json_prototyp[0]['fields']['bme280.temperature.raw'] = bme280.get_temperature()
            influx_json_prototyp[0]['fields']['bme280.temperature.compensated'] = compensated_temp

        influx_json_prototyp[0]['fields']['cpu.temperature'] = get_cpu_temperature()
        influx_json_prototyp[0]['fields']['bme280.pressure'] = bme280.get_pressure()
        influx_json_prototyp[0]['fields']['bme280.humidity'] = bme280.get_humidity()

        gas_data = gas.read_all()
        influx_json_prototyp[0]['fields']['mics6814.oxidising'] = gas_data.oxidising
        influx_json_prototyp[0]['fields']['mics6814.reducing'] = gas_data.reducing
        influx_json_prototyp[0]['fields']['mics6814.nh3'] = gas_data.nh3


        if iterations >= 3:
            print("Write points: {0}".format(influx_json_prototyp))
            influx.write_points(influx_json_prototyp, retention_policy="rp_1y")
        else:
            print("Skip iteration: " + str(iterations))

        time.sleep(10)
        iterations += 1

# Exit cleanly
except KeyboardInterrupt:
    sys.exit(0)

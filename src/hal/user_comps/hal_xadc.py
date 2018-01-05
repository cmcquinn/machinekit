#!/usr/bin/python2
# encoding: utf-8

########################################################################
# Description: hal_xadc.py                                             #
# This code reads an ADC input on the Xilinx Zynq.                     #
#                                                                      #
# Author(s): Cameron McQuinn                                           #
# Adapted from hal_temp_bbb.py                                         #
# License: GNU GPL Version 2.0 or (at your option) any later version.  #
#                                                                      #
# Major Changes:                                                       #
# 2013-June   Charles Steinkuehler                                     #
#             Initial version                                          #
# 2014-July   Alexander Roessler                                       #
#             Port to the R2Temp component                             #
# 2018-January Cameron McQuinn                                         #
#              Port to Xilinx Zynq                                     #
########################################################################
# Copyright (C) 2013  Charles Steinkuehler                             #
#                     <charles AT steinkuehler DOT net>                #
#                                                                      #
# This program is free software; you can redistribute it and/or        #
# modify it under the terms of the GNU General Public License          #
# as published by the Free Software Foundation; either version 2       #
# of the License, or (at your option) any later version.               #
#                                                                      #
# This program is distributed in the hope that it will be useful,      #
# but WITHOUT ANY WARRANTY; without even the implied warranty of       #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the        #
# GNU General Public License for more details.                         #
#                                                                      #
# You should have received a copy of the GNU General Public License    #
# along with this program; if not, write to the Free Software          #
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA        #
# 02110-1301, USA.                                                     #
#                                                                      #
# THE AUTHORS OF THIS PROGRAM ACCEPT ABSOLUTELY NO LIABILITY FOR       #
# ANY HARM OR LOSS RESULTING FROM ITS USE.  IT IS _EXTREMELY_ UNWISE   #
# TO RELY ON SOFTWARE ALONE FOR SAFETY.  Any machinery capable of      #
# harming persons must have provisions for completely removing power   #
# from all motors, etc, before persons enter any danger area.  All     #
# machinery must be designed to comply with local and national safety  #
# codes, and the authors of this software can not, and do not, take    #
# any responsibility for such compliance.                              #
########################################################################

import argparse
import glob
import sys
import time

import hal
from fdm.r2temp import R2Temp

# CRAMPS board:  A voltage divider is formed by a pull-up resistor,
# tied to 1.8V VDD_ADC, and thermistor, tied to ground.  The ADC
# directly reads the thermistor voltage (V_T).  All the thermistor
# current flows through the pull-up (I_PU), and those two values are
# used to calculate the thermistor resistance.  The pull-up resistance
# R_PU is 2k on the CRAMPS, and may be supplied to reuse this function
# for custom circuits.  V_adc is 1.8V, and resolution is 12 bits for
# 4096 possible values.

# Irrelevant to these calculations, in the CRAMPS, the voltage divider
# feeds a 4.7K resistor and two capacitors which form an RC filter to
# reduce noise.  The BBB presents almost no load on its ADC input pins
# (just leakage current through CMOS inputs), so there is essentially
# zero voltage across the 4.7K resistor unless the thermistor is
# changing value very rapidly (or there is noise on the line).

# https://groups.google.com/d/msg/machinekit/wZ8KAKqV7yo/blG1yZ0rBAAJ

def adc2r_replicookie(pin,
                  # Pull-up resistence 
                  R_PU = 2000,
                  # Pull-down resistance
                  R_PD = 2000):
    # Voltage across the thermistor
    V_T = pin.rawValue / 4096.0

    # Current flowing through the pull-up resistor
    # No dividing by zero or negative voltages despite what the ADC says!
    # Clip to a small positive value
    I_PU = max((1 - V_T ) / R_PU, 0.000001) 

    # Resistance of the thermistor
    R_T = (V_T / I_PU) - R_PD

    return R_T


class Pin:
    def __init__(self):
        self.pin = 'vaux'
        self.r2temp = None
        self.halValuePin = 0
        self.halRawPin = 0
        self.filterSamples = []
        self.filterSize = 10
        self.rawValue = 0.0
        self.filename = ""
        self.filterSamples = []
        self.rawValue = 0.0

    def addSample(self, value):
        self.filterSamples.append(value)
        if (len(self.filterSamples) > self.filterSize):
            self.filterSamples.pop(0)
        sampleSum = 0.0
        for sample in self.filterSamples:
            sampleSum += sample
        self.rawValue = sampleSum / len(self.filterSamples)


def adc2Temp(pin):
    if(args.baseboard == 'Replicookie'):
        R = adc2r_replicookie(pin)
    else:
        print("Invalid -b cape  name: %s" % args.baseboard)
        print("Valid names are: Replicookie")
        sys.exit(1)
    return round(pin.r2temp.r2t(R) * 10.0) / 10.0


def getHalName(pin):
    return pin.pin


def checkAdcInput(pin):
    syspath = '/sys/bus/iio/devices/iio:device0/'
    tempName = glob.glob(syspath + '*' + pin.pin + '_raw')
    pin.filename = tempName[0]
    try:
        if len(pin.filename) > 0:
            f = open(pin.filename, 'r')
            f.close()
            time.sleep(0.001)
        else:
            raise UserWarning('Bad Filename')
    except (UserWarning, IOError):
        print(("Cannot read ADC input: %s" % pin.filename))
        sys.exit(1)


parser = argparse.ArgumentParser(description='HAL component to read ADC values and convert to temperature')
parser.add_argument('-n','--name', help='HAL component name',required=True)
parser.add_argument('-i', '--interval', help='Adc update interval', default=0.05)
parser.add_argument('-c', '--channels', help='Komma separated list of channels and thermistors to use e.g. 01:semitec_103GT_2,02:epcos_B57560G1104', required=True)
parser.add_argument('-f', '--filter_size', help='Size of the low pass filter to use', default=10)
parser.add_argument('-b', '--baseboard', help='Type of baseboard used', default='Replicookie')
parser.add_argument('-r', '--r_pu', default=2000, type=float,
                    help='Divider pull-up resistor value (default 2k Ohms)')


args = parser.parse_args()

updateInterval = float(args.interval)
filterSize = int(args.filter_size)
error = False
watchdog = True

# Create pins
pins = []

if (args.channels != ""):
    channelsRaw = args.channels.split(',')
    for channel in channelsRaw:
        pinRaw = channel.split(':')
        pin = Pin()
        pin.pin = pinRaw[0]
        if (pin.pin == ""):
            print(("Pin not available"))
            sys.exit(1)
        checkAdcInput(pin)
        if (pinRaw[1] != "none"):
            pin.r2temp = R2Temp(pinRaw[1])
        pin.filterSize = filterSize
        pins.append(pin)


# Initialize HAL
h = hal.component(args.name)
for pin in pins:
    pin.halRawPin = h.newpin(getHalName(pin) + ".raw", hal.HAL_FLOAT, hal.HAL_OUT)
    if (pin.r2temp is not None):
        pin.halValuePin = h.newpin(getHalName(pin) + ".value", hal.HAL_FLOAT, hal.HAL_OUT)
halErrorPin = h.newpin("error", hal.HAL_BIT, hal.HAL_OUT)
halNoErrorPin = h.newpin("no-error", hal.HAL_BIT, hal.HAL_OUT)
halWatchdogPin = h.newpin("watchdog", hal.HAL_BIT, hal.HAL_OUT)
h.ready()

halErrorPin.value = error
halNoErrorPin.value = not error
halWatchdogPin.value = watchdog

try:
    while (True):
        try:
            for pin in pins:
                f = open(pin.filename, 'r')
                value = float(f.readline())
                pin.addSample(value)
                pin.halRawPin.value = pin.rawValue
                if (pin.r2temp is not None):
                    pin.halValuePin.value = adc2Temp(pin)
            error = False
        except IOError:
            error = True

        halErrorPin.value = error
        halNoErrorPin.value = not error
        watchdog = not watchdog
        halWatchdogPin.value = watchdog
        time.sleep(updateInterval)
except:
    print(("exiting HAL component " + args.name))
    h.exit()


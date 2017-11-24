# adc_dev.md

## This is to keep track of and plan the development of the ADC driver

Relevant Parts

## How does this thing work?

In the HAL file, the soc driver is instantantiated with a `loadrt` command.

A read on the ADC is called like so:

`hm2_<board_name>.<board_num>.*_soc_adc.ch.N.out`

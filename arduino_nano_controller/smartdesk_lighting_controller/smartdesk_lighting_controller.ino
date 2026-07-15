/*
 * SmartDesk Lighting Controller (Arduino Nano) — sketch entry point.
 *
 * This file is intentionally minimal: all hardware/serial/protocol logic
 * lives in SmartDeskLighting.{h,cpp}. The Nano is a host-driven lighting
 * executor — it parses text commands from the serial port and renders the
 * requested mode non-blocking.
 *
 * Protocol: arduino_nano_controller/protocol.md
 * Hardware: SR505 PIR -> D8, WS2812B -> D6, built-in LED -> D13, VL53L0X -> I2C.
 */

#include "SmartDeskLighting.h"

SmartDeskLighting controller;

void setup()
{
    controller.begin();
}

void loop()
{
    controller.update();
}

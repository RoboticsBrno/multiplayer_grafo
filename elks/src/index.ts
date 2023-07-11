import * as adc from "adc";
import * as radio from "simpleradio";
import * as gpio from "gpio";
import * as led from "smartled";
import * as colors from "./libs/colors.js";

const PIN_X = 2;
const PIN_Y = 1;

const PIN_JOYSTICK_X = 10;
const PIN_JOYSTICK_Y = 9;

let THICKNESS = 2;

const COLORS = ["#ff0000", "#00FF00", "#0000FF"];
let CUR_COLOR = 0;

function convert_adc(adc_value: number): number {
  const pct = (adc_value / 1023) * 100;

  // mrtvá zóna
  if (pct >= 40 && pct <= 60) {
    return 0;
  }

  if (pct < 50) {
    return Math.round((pct / 50) * 100 - 100);
  } else {
    return Math.round(((pct - 50) / 50) * 100);
  }
}

function convert_adc_accel(adc_value: number): number {
  let val = adc_value / 1023;

  // mrtvá zóna
  if (val >= 0.45 && val <= 0.55) {
    return 0;
  }

  if (val < 0.5) {
    val = val / 0.5;
    return Math.round(val * val * 100 - 100);
  } else {
    val = (val - 0.5) / 0.5;
    return Math.round(val * val * 100);
  }
}

async function main() {
  adc.configure(PIN_X);
  adc.configure(PIN_Y);

  adc.configure(PIN_JOYSTICK_X);
  adc.configure(PIN_JOYSTICK_Y);

  gpio.pinMode(18, gpio.PinMode.INPUT);
  gpio.pinMode(16, gpio.PinMode.INPUT);
  gpio.pinMode(42, gpio.PinMode.INPUT);

  radio.begin(12);

  let cooldown = Promise.resolve();

  gpio.on("rising", 18, async () => {
    THICKNESS++;
    if (THICKNESS > 10) {
      THICKNESS = 1;
    }

    await cooldown;
    radio.sendString(`t ${THICKNESS}`);
    cooldown = sleep(100);
  });

  gpio.on("rising", 16, async () => {
    await cooldown;
    radio.sendString("reset");
    cooldown = sleep(100);
  });

  gpio.on("rising", 42, async () => {
    CUR_COLOR++;
    if (CUR_COLOR >= COLORS.length) {
      CUR_COLOR = 0;
    }

    await cooldown;
    radio.sendString(`c ${COLORS[CUR_COLOR]}`);
    cooldown = sleep(100);
  });

  // Left is X, right is Y axis
  /*while (true) {
    const x = convert_adc(adc.read(PIN_X));
    const y = convert_adc(adc.read(PIN_Y)) * -1;

    await cooldown;
    radio.sendString(`s ${x} ${y}`);
    await sleep(50);
  }*/

  // Left is heading, right is speed
  /*
  while (true) {
    const heading = (1 - adc.read(PIN_X) / 1023) * 2 * Math.PI;
    const speed = 1 - adc.read(PIN_Y) / 1023;

    const x = Math.sin(heading) * speed * 100;
    const y = Math.cos(heading) * speed * 100;

    await cooldown;
    radio.sendString(`s ${x} ${y}`);
    await sleep(50);
  }*/

  // Joystick attached to PMOD_1
  while (true) {
    const x = convert_adc(adc.read(PIN_JOYSTICK_X)) * -1;
    const y = convert_adc(adc.read(PIN_JOYSTICK_Y)) * -1;
    await cooldown;
    radio.sendString(`s ${x} ${y}`);
    await sleep(50);
  }
}

main();

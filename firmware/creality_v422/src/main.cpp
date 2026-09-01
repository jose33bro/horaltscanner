#include <Arduino.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

namespace {

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t COMMAND_TIMEOUT_MS = 5000;
constexpr uint32_t HOME_TIMEOUT_MS = 120000;
constexpr uint32_t MAX_MOVE_STEPS = 200000;
constexpr uint32_t MIN_STEP_RATE = 1;
constexpr uint32_t MAX_STEP_RATE = 20000;
constexpr uint16_t STEP_PULSE_US = 4;

constexpr uint32_t ENABLE_PIN = PC3;
constexpr uint32_t HEATER_0_PIN = PA1;
constexpr uint32_t HEATER_BED_PIN = PA2;
constexpr uint32_t FAN_PA0_PIN = PA0;
constexpr uint32_t FAN_PA8_PIN = PA8;
constexpr uint32_t TEMP_PC5_PIN = PC5;

struct Axis {
  char name;
  uint32_t step_pin;
  uint32_t dir_pin;
  uint32_t endstop_pin;
  bool direction_inverted;
  bool endstop_active_high;
  uint32_t start_step_rate;
  uint32_t home_step_rate;
};

constexpr Axis AXES[] = {
    {'X', PC2, PB9, PA5, false, true, 100, 400},
    {'Y', PB8, PB7, PA6, true, true, 20, 100},
    {'Z', PB6, PB5, PA7, true, true, 100, 400},
};
constexpr size_t AXIS_COUNT = sizeof(AXES) / sizeof(AXES[0]);

char command_buffer[96];
size_t command_length = 0;
uint8_t fan_pa0 = 0;
uint8_t fan_pa8 = 0;
uint32_t last_command_ms = 0;
bool steppers_enabled = false;

enum class MotionType { IDLE, MOVE, HOME };
enum class MotionResult { DONE, RUNNING, STOPPED, ERROR };

MotionType motion_type = MotionType::IDLE;
MotionResult motion_result = MotionResult::DONE;
const Axis *motion_axis = nullptr;
uint32_t motion_steps_remaining = 0;
uint32_t motion_steps_completed = 0;
uint32_t motion_period_us = 0;
uint32_t motion_start_rate = 0;
uint32_t motion_target_rate = 0;
uint32_t motion_ramp_steps = 1;
uint32_t motion_next_edge_us = 0;
uint32_t motion_deadline_ms = 0;
uint8_t home_axis_index = 0;
bool home_all = false;
bool motion_positive = false;
bool step_pin_high = false;

Axis const *findAxis(char name) {
  for (const Axis &axis : AXES) {
    if (axis.name == name) return &axis;
  }
  return nullptr;
}

void setSteppersEnabled(bool enabled) {
  digitalWrite(ENABLE_PIN, enabled ? LOW : HIGH);
  steppers_enabled = enabled;
}

bool endstopTriggered(const Axis &axis) {
  return digitalRead(axis.endstop_pin) == (axis.endstop_active_high ? HIGH : LOW);
}

void setDirection(const Axis &axis, bool positive) {
  const bool high = positive ^ axis.direction_inverted;
  digitalWrite(axis.dir_pin, high ? HIGH : LOW);
}

void serviceFanPa0() {
  static uint32_t cycle_started_us = 0;
  const uint32_t now = micros();
  const uint32_t elapsed = now - cycle_started_us;
  if (elapsed >= 10000) cycle_started_us = now;
  const uint32_t on_time_us = static_cast<uint32_t>(fan_pa0) * 10000U / 255U;
  digitalWrite(FAN_PA0_PIN, fan_pa0 > 0 && (now - cycle_started_us) < on_time_us);
}

void finishMotion(MotionResult result);

void serviceSafety() {
  serviceFanPa0();
  if (motion_type != MotionType::IDLE &&
      millis() - last_command_ms > COMMAND_TIMEOUT_MS) {
    finishMotion(MotionResult::ERROR);
  }
}

void finishMotion(MotionResult result) {
  if (motion_axis) digitalWrite(motion_axis->step_pin, LOW);
  setSteppersEnabled(false);
  motion_type = MotionType::IDLE;
  motion_result = result;
  motion_axis = nullptr;
  step_pin_high = false;
}

void updateMotionPeriod() {
  uint32_t ramp_position = min(motion_steps_completed + 1, motion_ramp_steps);
  if (motion_type == MotionType::MOVE) {
    ramp_position = min(ramp_position, motion_steps_remaining + 1);
  }
  const uint32_t rate_delta = motion_target_rate - motion_start_rate;
  const uint32_t rate =
      motion_start_rate + (rate_delta * ramp_position) / motion_ramp_steps;
  motion_period_us = 1000000U / (rate == 0 ? 1 : rate);
}

void beginHomeAxis(uint8_t index) {
  home_axis_index = index;
  motion_axis = &AXES[index];
  if (endstopTriggered(*motion_axis)) {
    if (home_all && static_cast<size_t>(index + 1) < AXIS_COUNT) {
      beginHomeAxis(index + 1);
    } else {
      finishMotion(MotionResult::DONE);
    }
    return;
  }
  setDirection(*motion_axis, false);
  motion_steps_completed = 0;
  motion_start_rate = motion_axis->start_step_rate;
  motion_target_rate = motion_axis->home_step_rate;
  motion_ramp_steps = 100;
  updateMotionPeriod();
  motion_next_edge_us = micros();
  motion_deadline_ms = millis() + HOME_TIMEOUT_MS;
  motion_type = MotionType::HOME;
  motion_result = MotionResult::RUNNING;
  setSteppersEnabled(true);
}

bool beginMove(const Axis &axis, int32_t steps, uint32_t rate) {
  if (motion_type != MotionType::IDLE || steps == 0) return steps == 0;
  motion_axis = &axis;
  motion_positive = steps > 0;
  motion_steps_remaining = static_cast<uint32_t>(labs(steps));
  motion_steps_completed = 0;
  motion_start_rate = min(axis.start_step_rate, rate);
  motion_target_rate = rate;
  motion_ramp_steps = motion_steps_remaining / 2U;
  if (motion_ramp_steps == 0) motion_ramp_steps = 1;
  if (motion_ramp_steps > 100) motion_ramp_steps = 100;
  updateMotionPeriod();
  motion_next_edge_us = micros();
  motion_type = MotionType::MOVE;
  motion_result = MotionResult::RUNNING;
  last_command_ms = millis();
  step_pin_high = false;
  setDirection(axis, motion_positive);
  setSteppersEnabled(true);
  return true;
}

bool beginHome(const Axis *axis) {
  if (motion_type != MotionType::IDLE) return false;
  last_command_ms = millis();
  home_all = axis == nullptr;
  beginHomeAxis(axis ? static_cast<uint8_t>(axis - AXES) : 0);
  return true;
}

void serviceMotion() {
  if (motion_type == MotionType::IDLE || motion_axis == nullptr) return;

  if (motion_type == MotionType::HOME) {
    if (endstopTriggered(*motion_axis)) {
      digitalWrite(motion_axis->step_pin, LOW);
      step_pin_high = false;
      if (home_all && static_cast<size_t>(home_axis_index + 1) < AXIS_COUNT) {
        beginHomeAxis(home_axis_index + 1);
      } else {
        finishMotion(MotionResult::DONE);
      }
      return;
    }
    if (static_cast<int32_t>(millis() - motion_deadline_ms) >= 0) {
      finishMotion(MotionResult::ERROR);
      return;
    }
  } else if (motion_axis->name != 'Y' && !motion_positive &&
             endstopTriggered(*motion_axis)) {
    finishMotion(MotionResult::DONE);
    return;
  }

  const uint32_t now = micros();
  if (static_cast<int32_t>(now - motion_next_edge_us) < 0) return;

  if (!step_pin_high) {
    if (motion_type == MotionType::MOVE && motion_steps_remaining == 0) {
      finishMotion(MotionResult::DONE);
      return;
    }
    digitalWrite(motion_axis->step_pin, HIGH);
    step_pin_high = true;
    motion_next_edge_us = now + STEP_PULSE_US;
  } else {
    digitalWrite(motion_axis->step_pin, LOW);
    step_pin_high = false;
    if (motion_type == MotionType::MOVE) --motion_steps_remaining;
    ++motion_steps_completed;
    updateMotionPeriod();
    motion_next_edge_us =
        now + (motion_period_us > STEP_PULSE_US ? motion_period_us - STEP_PULSE_US : 1);
  }
}

bool parseLong(const char *text, long &value) {
  if (!text || !*text) return false;
  char *end = nullptr;
  value = strtol(text, &end, 10);
  return end && *end == '\0';
}

void printError(const char *message) {
  Serial1.print("ERR ");
  Serial1.println(message);
}

void printTemperature() {
  constexpr float SERIES_RESISTOR_OHMS = 4700.0f;
  constexpr float NOMINAL_RESISTANCE_OHMS = 100000.0f;
  constexpr float NOMINAL_TEMP_K = 25.0f + 273.15f;
  constexpr float BETA = 4092.0f;

  const uint32_t adc = analogRead(TEMP_PC5_PIN);
  if (adc <= 1 || adc >= 4094) {
    printError("TEMP_SENSOR");
    return;
  }
  const float resistance = SERIES_RESISTOR_OHMS * adc / (4095.0f - adc);
  const float inverse_temp =
      (1.0f / NOMINAL_TEMP_K) + logf(resistance / NOMINAL_RESISTANCE_OHMS) / BETA;
  const float celsius = (1.0f / inverse_temp) - 273.15f;
  if (!isfinite(celsius) || celsius < -50.0f || celsius > 150.0f) {
    printError("TEMP_RANGE");
    return;
  }
  Serial1.print("OK TEMP_PC5 ");
  Serial1.println(celsius, 1);
}

void processCommand(char *line) {
  char *verb = strtok(line, " ");
  if (!verb) return;

  if (strcmp(verb, "PING") == 0) {
    Serial1.println("OK PONG");
    return;
  }

  if (strcmp(verb, "MOVE") == 0) {
    const char *axis_text = strtok(nullptr, " ");
    const char *steps_text = strtok(nullptr, " ");
    const char *rate_text = strtok(nullptr, " ");
    long steps = 0;
    long rate = 0;
    const Axis *axis = axis_text && axis_text[1] == '\0' ? findAxis(axis_text[0]) : nullptr;
    if (!axis || !parseLong(steps_text, steps) || !parseLong(rate_text, rate) ||
        steps < -static_cast<long>(MAX_MOVE_STEPS) ||
        steps > static_cast<long>(MAX_MOVE_STEPS) ||
        rate < static_cast<long>(MIN_STEP_RATE) ||
        rate > static_cast<long>(MAX_STEP_RATE) ||
        !beginMove(*axis, static_cast<int32_t>(steps), static_cast<uint32_t>(rate))) {
      printError("MOVE");
      return;
    }
    Serial1.println("OK MOVE");
    return;
  }

  if (strcmp(verb, "HOME") == 0) {
    const char *axis_text = strtok(nullptr, " ");
    if (!axis_text) {
      printError("HOME");
      return;
    }
    const bool all = strcmp(axis_text, "ALL") == 0;
    const Axis *axis = !all && axis_text[1] == '\0' ? findAxis(axis_text[0]) : nullptr;
    if ((!all && !axis) || !beginHome(all ? nullptr : axis)) {
      printError("HOME");
      return;
    }
    Serial1.println("OK HOME");
    return;
  }

  if (strcmp(verb, "ENDSTOP") == 0) {
    const char *axis_text = strtok(nullptr, " ");
    const Axis *axis = axis_text && axis_text[1] == '\0' ? findAxis(axis_text[0]) : nullptr;
    if (!axis) {
      printError("ENDSTOP");
      return;
    }
    Serial1.print("OK ENDSTOP ");
    Serial1.println(endstopTriggered(*axis) ? 1 : 0);
    return;
  }

  if (strcmp(verb, "SYNC") == 0) {
    const char *token = strtok(nullptr, " ");
    if (!token) {
      printError("SYNC");
      return;
    }
    Serial1.print("OK SYNC ");
    Serial1.println(token);
    return;
  }

  if (strcmp(verb, "STOP") == 0) {
    finishMotion(MotionResult::STOPPED);
    Serial1.println("OK STOP");
    return;
  }

  if (strcmp(verb, "MOTION_STATUS") == 0) {
    if (motion_result == MotionResult::RUNNING) last_command_ms = millis();
    Serial1.print("OK MOTION_STATUS ");
    switch (motion_result) {
      case MotionResult::RUNNING: Serial1.println("RUNNING"); break;
      case MotionResult::STOPPED: Serial1.println("STOPPED"); break;
      case MotionResult::ERROR: Serial1.println("ERROR"); break;
      default: Serial1.println("DONE"); break;
    }
    return;
  }

  if (strcmp(verb, "FAN_PA0_PWM") == 0 || strcmp(verb, "FAN_PA8_PWM") == 0) {
    const bool pa0 = strcmp(verb, "FAN_PA0_PWM") == 0;
    const char *value_text = strtok(nullptr, " ");
    long value = 0;
    if (!parseLong(value_text, value) || value < 0 || value > 255) {
      printError("FAN");
      return;
    }
    if (pa0) {
      fan_pa0 = static_cast<uint8_t>(value);
    } else {
      fan_pa8 = static_cast<uint8_t>(value);
      analogWrite(FAN_PA8_PIN, fan_pa8);
    }
    Serial1.println(pa0 ? "OK FAN_PA0_PWM" : "OK FAN_PA8_PWM");
    return;
  }

  if (strcmp(verb, "TEMP_PC5_READ") == 0) {
    printTemperature();
    return;
  }

  printError("UNKNOWN_COMMAND");
}

}  // namespace

void setup() {
  pinMode(ENABLE_PIN, OUTPUT);
  pinMode(HEATER_0_PIN, OUTPUT);
  pinMode(HEATER_BED_PIN, OUTPUT);
  pinMode(FAN_PA0_PIN, OUTPUT);
  pinMode(FAN_PA8_PIN, OUTPUT);
  digitalWrite(HEATER_0_PIN, LOW);
  digitalWrite(HEATER_BED_PIN, LOW);
  digitalWrite(FAN_PA0_PIN, LOW);
  digitalWrite(FAN_PA8_PIN, LOW);
  setSteppersEnabled(false);

  for (const Axis &axis : AXES) {
    pinMode(axis.step_pin, OUTPUT);
    pinMode(axis.dir_pin, OUTPUT);
    pinMode(axis.endstop_pin, INPUT_PULLUP);
    digitalWrite(axis.step_pin, LOW);
  }

  analogReadResolution(12);
  analogWriteResolution(8);
  Serial1.begin(SERIAL_BAUD);
  last_command_ms = millis();
}

void loop() {
  serviceSafety();
  serviceMotion();
  while (Serial1.available()) {
    const char value = static_cast<char>(Serial1.read());
    if (value == '\n' || value == '\r') {
      if (command_length > 0) {
        command_buffer[command_length] = '\0';
        processCommand(command_buffer);
        command_length = 0;
      }
    } else if (command_length < sizeof(command_buffer) - 1) {
      command_buffer[command_length++] = value;
    } else {
      command_length = 0;
      printError("COMMAND_TOO_LONG");
    }
  }
}

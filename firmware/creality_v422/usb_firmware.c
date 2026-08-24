#include <stdbool.h>
#include <stdint.h>
#include "src/adc.h"
#include "src/temperature.h"
#include "src/fan_control.h"

#define AXIS_X_MIN_STEPS 0
#define AXIS_X_MAX_STEPS 200000
#define AXIS_Y_STEPS_PER_TURN 6400
#define AXIS_Z_MIN_STEPS 0
#define AXIS_Z_MAX_STEPS 120000

#define STATUS_OK 0x00
#define STATUS_ERROR 0x01

#define ERR_NONE 0x00
#define ERR_BAD_CHECKSUM 0x10
#define ERR_BAD_COMMAND 0x11
#define ERR_OUT_OF_RANGE 0x12
#define ERR_THERMAL_SHUTDOWN 0x20

typedef enum {
    AXIS_X = 0,
    AXIS_Y = 1,
    AXIS_Z = 2
} axis_id_t;

typedef enum {
    CMD_MOVE_X = 0x01,
    CMD_MOVE_Y = 0x02,
    CMD_MOVE_Z = 0x03,
    CMD_HOME_X = 0x10,
    CMD_HOME_Y = 0x11,
    CMD_HOME_Z = 0x12,
    CMD_SET_SPEED = 0x20,
    CMD_GET_STATUS = 0x30,
    CMD_STOP = 0x40,
    CMD_GET_TEMP = 0x50,
    CMD_FAN_ON = 0x51,
    CMD_FAN_OFF = 0x52,
    CMD_SET_FAN_THRESHOLD = 0x53
} command_id_t;

typedef struct __attribute__((packed)) {
    uint8_t command;
    uint8_t axis;
    int32_t value;
    int32_t speed;
    uint8_t checksum;
} usb_packet_t;

typedef struct __attribute__((packed)) {
    uint8_t status;
    uint8_t error;
    int32_t pos_x;
    int32_t pos_y;
    int32_t pos_z;
    uint8_t endstop_mask;
    int16_t temperature_cdeg; /* temperature in centi-degrees Celsius (value / 100 = °C) */
    uint8_t checksum;
} usb_response_t;

typedef struct {
    int32_t position_steps;
    int32_t speed_steps_per_s;
    bool endstop;
} axis_state_t;

static axis_state_t g_axes[3];

__attribute__((weak))
void motor_stepper_move(axis_id_t axis, int32_t delta_steps, int32_t speed_steps_per_s) {
    (void)axis;
    (void)delta_steps;
    (void)speed_steps_per_s;
}

__attribute__((weak))
void motor_stepper_stop_all(void) {}

__attribute__((weak))
void motor_stepper_home(axis_id_t axis) {
    (void)axis;
}

static uint8_t checksum_xor(const uint8_t *data, uint32_t len) {
    uint8_t result = 0;
    for (uint32_t i = 0; i < len; ++i) {
        result ^= data[i];
    }
    return result;
}

static bool axis_in_range(axis_id_t axis, int32_t position) {
    if (axis == AXIS_X) {
        return position >= AXIS_X_MIN_STEPS && position <= AXIS_X_MAX_STEPS;
    }
    if (axis == AXIS_Y) {
        return true;
    }
    return position >= AXIS_Z_MIN_STEPS && position <= AXIS_Z_MAX_STEPS;
}

static void axis_refresh_endstop(axis_id_t axis) {
    if (axis == AXIS_Y) {
        g_axes[AXIS_Y].endstop = (g_axes[AXIS_Y].position_steps % AXIS_Y_STEPS_PER_TURN) == 0;
        return;
    }
    g_axes[axis].endstop = g_axes[axis].position_steps == 0;
}

static uint8_t get_endstop_mask(void) {
    uint8_t mask = 0;
    if (g_axes[AXIS_X].endstop) {
        mask |= (1u << AXIS_X);
    }
    if (g_axes[AXIS_Y].endstop) {
        mask |= (1u << AXIS_Y);
    }
    if (g_axes[AXIS_Z].endstop) {
        mask |= (1u << AXIS_Z);
    }
    return mask;
}

void firmware_init(void) {
    g_axes[AXIS_X] = (axis_state_t){.position_steps = 0, .speed_steps_per_s = 2000, .endstop = true};
    g_axes[AXIS_Y] = (axis_state_t){.position_steps = 0, .speed_steps_per_s = 1500, .endstop = true};
    g_axes[AXIS_Z] = (axis_state_t){.position_steps = 0, .speed_steps_per_s = 1200, .endstop = true};
    adc_init();
    fan_control_init(0); /* relay on GPIO PB0 by default */
}

static uint8_t axis_move(axis_id_t axis, int32_t delta_steps, int32_t speed_steps_per_s) {
    int32_t target = g_axes[axis].position_steps + delta_steps;
    if (!axis_in_range(axis, target)) {
        return ERR_OUT_OF_RANGE;
    }

    if (speed_steps_per_s > 0) {
        g_axes[axis].speed_steps_per_s = speed_steps_per_s;
    }

    motor_stepper_move(axis, delta_steps, g_axes[axis].speed_steps_per_s);
    g_axes[axis].position_steps = target;
    axis_refresh_endstop(axis);
    return ERR_NONE;
}

static void fill_response(usb_response_t *response, uint8_t status, uint8_t error) {
    response->status = status;
    response->error = error;
    response->pos_x = g_axes[AXIS_X].position_steps;
    response->pos_y = g_axes[AXIS_Y].position_steps;
    response->pos_z = g_axes[AXIS_Z].position_steps;
    response->endstop_mask = get_endstop_mask();
    float temp_c = temperature_read_celsius();
    response->temperature_cdeg = (int16_t)(temp_c * 100.0f);
    response->checksum = checksum_xor((const uint8_t *)response, sizeof(usb_response_t) - 1);
}

void firmware_handle_packet(const usb_packet_t *packet, usb_response_t *response) {
    const uint8_t expected = checksum_xor((const uint8_t *)packet, sizeof(usb_packet_t) - 1);
    if (packet->checksum != expected) {
        fill_response(response, STATUS_ERROR, ERR_BAD_CHECKSUM);
        return;
    }

    /* Emergency thermal safety: stop all motors if temperature exceeds limit. */
    float current_temp = temperature_read_celsius();
    fan_control_update(current_temp);
    if (current_temp >= TEMP_EMERGENCY_STOP) {
        motor_stepper_stop_all();
        fill_response(response, STATUS_ERROR, ERR_THERMAL_SHUTDOWN);
        return;
    }

    uint8_t error = ERR_NONE;
    switch ((command_id_t)packet->command) {
        case CMD_MOVE_X:
            error = axis_move(AXIS_X, packet->value, packet->speed);
            break;
        case CMD_MOVE_Y:
            error = axis_move(AXIS_Y, packet->value, packet->speed);
            break;
        case CMD_MOVE_Z:
            error = axis_move(AXIS_Z, packet->value, packet->speed);
            break;
        case CMD_HOME_X:
            motor_stepper_home(AXIS_X);
            g_axes[AXIS_X].position_steps = 0;
            axis_refresh_endstop(AXIS_X);
            break;
        case CMD_HOME_Y:
            motor_stepper_home(AXIS_Y);
            g_axes[AXIS_Y].position_steps = 0;
            axis_refresh_endstop(AXIS_Y);
            break;
        case CMD_HOME_Z:
            motor_stepper_home(AXIS_Z);
            g_axes[AXIS_Z].position_steps = 0;
            axis_refresh_endstop(AXIS_Z);
            break;
        case CMD_SET_SPEED:
            if (packet->axis > AXIS_Z || packet->speed <= 0) {
                error = ERR_BAD_COMMAND;
                break;
            }
            g_axes[packet->axis].speed_steps_per_s = packet->speed;
            break;
        case CMD_GET_STATUS:
            break;
        case CMD_STOP:
            motor_stepper_stop_all();
            break;
        case CMD_GET_TEMP:
            /* Temperature is always embedded in the response; nothing extra needed. */
            break;
        case CMD_FAN_ON:
            fan_on();
            break;
        case CMD_FAN_OFF:
            fan_off();
            break;
        case CMD_SET_FAN_THRESHOLD: {
            /* value  = on  threshold * 100 (centi-degrees)
             * speed  = off threshold * 100 (centi-degrees) */
            float th_on  = (float)packet->value / 100.0f;
            float th_off = (float)packet->speed / 100.0f;
            if (th_on <= th_off) {
                error = ERR_BAD_COMMAND;
                break;
            }
            fan_set_threshold(th_on, th_off);
            break;
        }
        default:
            error = ERR_BAD_COMMAND;
            break;
    }

    fill_response(response, error == ERR_NONE ? STATUS_OK : STATUS_ERROR, error);
}

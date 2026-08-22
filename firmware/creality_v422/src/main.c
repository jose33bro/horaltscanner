#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CMD_BUF_SIZE 96

static bool y_endstop_triggered(void) {
    // À connecter au GPIO réel de l'endstop Y.
    return false;
}

static void motor_move(char axis, int32_t steps, int32_t speed) {
    // À connecter aux drivers pas-à-pas (X/Y/Z) de la carte V4.2.2.
    (void)axis;
    (void)steps;
    (void)speed;
}

static void motor_home_y(void) {
    // Homing simplifié: avance/recul jusqu'à endstop Y (point 0 lidar).
    while (!y_endstop_triggered()) {
        motor_move('Y', -1, 200);
    }
}

static void usb_write_line(const char *line) {
    // À connecter à la pile USB CDC STM32.
    (void)line;
}

static void respond_ok(const char *suffix) {
    char out[CMD_BUF_SIZE];
    snprintf(out, sizeof(out), "OK %s\n", suffix);
    usb_write_line(out);
}

static void respond_err(const char *suffix) {
    char out[CMD_BUF_SIZE];
    snprintf(out, sizeof(out), "ERR %s\n", suffix);
    usb_write_line(out);
}

static void handle_command(const char *line) {
    if (strcmp(line, "PING") == 0) {
        respond_ok("PONG");
        return;
    }

    char axis = 0;
    int32_t steps = 0;
    int32_t speed = 0;
    if (sscanf(line, "MOVE %c %ld %ld", &axis, &steps, &speed) == 3) {
        if (axis == 'X' || axis == 'Y' || axis == 'Z') {
            motor_move(axis, steps, speed);
            respond_ok("MOVE");
            return;
        }
        respond_err("AXIS");
        return;
    }

    if (strcmp(line, "HOME Y") == 0) {
        motor_home_y();
        respond_ok("HOME");
        return;
    }

    if (strcmp(line, "ENDSTOP Y") == 0) {
        respond_ok(y_endstop_triggered() ? "ENDSTOP 1" : "ENDSTOP 0");
        return;
    }

    char token[48];
    if (sscanf(line, "SYNC %47s", token) == 1) {
        char sync_payload[64];
        snprintf(sync_payload, sizeof(sync_payload), "SYNC %s", token);
        respond_ok(sync_payload);
        return;
    }

    respond_err("UNKNOWN");
}

int main(void) {
    // Boucle firmware simplifiée (la réception USB doit remplir cmd_buffer).
    char cmd_buffer[CMD_BUF_SIZE];
    (void)cmd_buffer;
    return 0;
}

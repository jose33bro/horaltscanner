#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
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

static bool motor_home_y(void) {
    // Homing simplifié: avance/recul jusqu'à endstop Y (point 0 lidar).
    const int32_t max_homing_steps = 200000;
    int32_t traveled = 0;
    while (!y_endstop_triggered()) {
        if (traveled >= max_homing_steps) {
            return false;
        }
        motor_move('Y', -1, 200);
        traveled++;
    }
    return true;
}

static void usb_write_line(const char *line) {
    // À connecter à la pile USB CDC STM32.
    (void)line;
}

static bool usb_read_line(char *buffer, size_t size) {
    // À connecter à la réception USB CDC STM32.
    // Contrat attendu: buffer est toujours null-terminé si true est renvoyé.
    (void)buffer;
    (void)size;
    return false;
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
    if (sscanf(line, "MOVE %c %" SCNd32 " %" SCNd32, &axis, &steps, &speed) == 3) {
        if (axis == 'X' || axis == 'Y' || axis == 'Z') {
            motor_move(axis, steps, speed);
            respond_ok("MOVE");
            return;
        }
        respond_err("AXIS");
        return;
    }

    if (strcmp(line, "HOME Y") == 0) {
        if (!motor_home_y()) {
            respond_err("HOME_TIMEOUT");
            return;
        }
        respond_ok("HOME");
        return;
    }

    if (strcmp(line, "ENDSTOP Y") == 0) {
        respond_ok(y_endstop_triggered() ? "ENDSTOP 1" : "ENDSTOP 0");
        return;
    }

    char token[48];
    if (sscanf(line, "SYNC %47s", token) == 1) {
        char sync_payload[CMD_BUF_SIZE];
        snprintf(sync_payload, sizeof(sync_payload), "SYNC %s", token);
        respond_ok(sync_payload);
        return;
    }

    respond_err("UNKNOWN");
}

int main(void) {
    // Boucle firmware simplifiée: la réception USB alimente cmd_buffer.
    char cmd_buffer[CMD_BUF_SIZE];
    while (true) {
        if (usb_read_line(cmd_buffer, sizeof(cmd_buffer))) {
            cmd_buffer[CMD_BUF_SIZE - 1] = '\0';
            handle_command(cmd_buffer);
        }
    }
}

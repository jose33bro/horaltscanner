# HoralScanner — Assembly Guide

## Overview
Step-by-step instructions for assembling the HoralScanner mechanical and electrical systems. Estimated time: **4–6 hours** for first build.

---

## Pre-Assembly Checklist

- [ ] All parts from [BOM.md](BOM.md) sourced and verified
- [ ] Raspberry Pi OS (Bookworm) flashed to SD card
- [ ] Soldering iron & solder ready (for GPIO connections)
- [ ] 3D-printed PLA parts cleaned (no support material stuck)
- [ ] Work surface clean and well-lit
- [ ] Multimeter available for continuity checks

---

## Phase 1: Motion Platform Base (Creality Hyper)

### Step 1.1: Assemble Frame
1. Mount the **Creality V4.2.2 board** on the **motion platform base** using M3 screws
   - Ensure power connector faces accessible direction (rear or side)
   - Verify no components interfere with motor mounts

2. Mount **NEMA 17 stepper motors** to the motor mounts:
   - **X-axis motor** → Left side, horizontal orientation
   - **Y-axis motor** → Center, horizontal orientation  
   - **Z-axis motor** → Right side, vertical orientation
   - Use M3 machine screws (4 per motor)

### Step 1.2: Install Ball Screw Assemblies
For each axis (X, Y, Z):
1. Thread **M5 × 40 ball screw** into the stepper motor coupler
2. Secure with M5 lock nut (0.8 pitch)
3. Ensure **ball Ø6.5 mm** sits freely in the ball nut (no binding)
4. Mount bearing blocks at each end:
   - **Rear bearing** (fixed) — M5 tapped hole in base plate
   - **Front bearing** (floating) — Adjustable M5 hole for preload

### Step 1.3: Configure Motion Axes

**X-Axis (Rotating Platform):**
- Ball screw orientation: **Horizontal, left-to-right**
- Coupling: motor shaft → ball screw (flexible coupler preferred)
- Platform attachment: bearing block → rotating table clamp

**Y-Axis (Linear Translation):**
- Ball screw orientation: **Horizontal, rear-to-front**
- Travel range: 0–100 mm (adjust for your build)
- Endstop: Mount **microswitch** at Y=0 (rear limit)
- Cable routing: Route USB (TF-Luna) along Y-carriage with drag chain

**Z-Axis (Height Adjustment):**
- Ball screw orientation: **Vertical, bottom-to-top**
- Travel range: 0–50 mm (camera height clearance)
- Soft limits: motor_control will enforce in firmware
- **Vertical Offset Calibration:** Set Z=0 reference **+5 mm above lowest position**
  - This allows TF-Luna (mounted on Y-carriage) to measure at optimal distance

---

## Phase 2: Camera Support Assembly

### Step 2.1: Prepare PLA Parts
1. Inspect **Camera Support Plate** (28.05 × 7 × 1 mm):
   - Verify **socket Ø6.9 mm** is centered (measure with caliper)
   - Check **4 mm petal retainers** for any print defects
   - Drill/ream M3 clearance holes if needed (target Ø3.2 mm)

2. Inspect **Base Plate**:
   - Verify **M5 tapped hole** is clean (test-thread a screw; back out cleanly)
   - Check **orientation marking** (rear → front label visible)
   - Measure **+5 mm vertical offset** from origin

### Step 2.2: Mount Camera Support Plate
1. Position **Camera Support Plate** on Z-carriage (top of Z-axis):
   - Align **socket Ø6.9** with Logitech USB camera lens
   - Ensure **rear → front orientation** matches Y-carriage direction
   - Leave **1 mm clearance** from ball screw

2. Fasten with **M3 screws** through both clearance holes:
   - Recommended: M3×10 pan-head (nylon or stainless)
   - Torque: 1.5–2 N·m (avoid stripping PLA)
   - Verify plate is level (use small spirit level)

3. Insert **Logitech USB camera** into socket:
   - Push gently until lens contacts socket walls
   - **4 mm petal retainers** should grip connector housing
   - Do NOT force (risk breaking petals)
   - Verify camera is horizontal and points downward at ~45°

### Step 2.3: Secure Cables
1. Route **USB camera cable** along Y-carriage using cable ties
2. Route to rear of frame; connect to **Raspberry Pi USB 2.0 port**
3. Leave **100 mm slack** for Y-axis motion (to avoid binding)

---

## Phase 3: Sensor Integration

### Step 3.1: TF-Luna LiDAR Mounting
1. Mount **TF-Luna on Y-carriage** (same as camera, parallel orientation):
   - Optical axis points **downward (Z-negative)**
   - Position **50 mm ahead of camera** (toward front of frame)
   - Use mounting bracket or 3D-printed holder (Ø16 mm typical)

2. Connect USB to **Raspberry Pi USB 2.0 port** (or via USB hub)
3. Verify LiDAR has clear view of object below (no obstructions)

### Step 3.2: Endstop Sensor (Y-Axis)
1. Mount **microswitch (NO)** at Y=0 (rear limit):
   - Position so Y-carriage contacts lever at soft limit
   - Solder connections: common → GND, NO → Creality endstop pin

2. Electrically connect to **Creality V4.2.2 endstop header** (pull-up enabled in firmware)

### Step 3.3: Thermistor (Board Temp)
- Already integrated in Creality V4.2.2 (PC5 ADC)
- No assembly required; verify firmware reads correctly in dashboard

---

## Phase 4: GPIO Wiring (Raspberry Pi)

### Step 4.1: Laser Outputs
1. **Laser Left (GPIO 27)**:
   - Connect laser +5V input to Pi 5V rail (via 330Ω resistor)
   - Connect laser GND to Pi GND
   - Connect laser trigger (if available) to GPIO 27 (digital output, 3.3V)
   - **Safety:** Test with multimeter before powering laser

2. **Laser Right (GPIO 22)**:
   - Follow same pattern as Left laser
   - Verify both lasers fire when dashboard toggles them

### Step 4.2: LED RGB Control
1. **LED Red (GPIO 18 PWM)**:
   - Connect LED anode to +5V rail
   - Connect LED cathode to GPIO 18 via 330Ω resistor + 2N2222 transistor
   - Transistor base → GPIO 18 (3.3V → 5V level conversion)

2. **LED Green (GPIO 13 PWM)** and **LED Blue (GPIO 19 PWM)**:
   - Repeat same pattern for each color
   - Verify all three colors blend properly on dashboard

### Step 4.3: Cooling Fan (GPIO 23)
1. Connect **5V fan** to Pi GPIO 23 with transistor driver:
   - Fan +5V → +5V rail
   - Fan GND → Transistor collector → GPIO 23
   - Fan will auto-start at 55°C, stop at 45°C

2. Test: Run `watch vcgencmd measure_temp` and confirm fan spins above threshold

### Step 4.4: Cable Management
- Use **Dupont jumper wires (F-F)** for all GPIO connections
- Label each wire with masking tape (e.g., "GPIO27_LaserLeft")
- Route cables away from motor wiring (avoid EMI)
- Secure with cable ties; leave 50 mm slack at connector ends

---

## Phase 5: Power & Communication

### Step 5.1: USB Connections (Raspberry Pi)
1. **Creality V4.2.2** → Pi USB 2.0 Port (Micro-USB):
   - Use **high-quality data-capable cable** (not power-only)
   - Verify connection: `lsusb` should show STM32 device
   - Check: `ls -l /dev/ttyUSB*` (should see `/dev/ttyUSB0` or similar)

2. **TF-Luna LiDAR** → Pi USB 2.0 Port:
   - Route USB parallel to camera cable
   - Verify: `cat /dev/ttyUSB1` shows distance readings (numbers, not gibberish)

3. **Logitech USB Camera** → Pi USB 2.0 Port:
   - Already connected in Phase 2.3
   - Verify: `ls /dev/video*` shows `/dev/video0`

### Step 5.2: Power Supply
1. Connect **24V PSU** to:
   - Creality V4.2.2 power jack (2.1mm barrel or XT60)
   - Raspberry Pi via USB-C power supply (separate 5V, 3A minimum)
   
2. Test polarity with **multimeter** before connecting boards

3. Power sequence:
   - Turn ON Creality 24V first
   - Then turn ON Pi 5V
   - (Reverse order when shutting down)

### Step 5.3: DSI Camera (Pi Camera V3, Optional)
1. Open **DSI ribbon connector** on Raspberry Pi (pull blue tab gently)
2. Insert **22-pin ribbon cable** until it clicks
3. Camera module should be mounted **above the X-axis platform** with 45° downward tilt

---

## Phase 6: Software & Firmware Setup

### Step 6.1: Flash Raspberry Pi OS
```bash
# On your workstation:
# 1. Download Raspberry Pi Imager
# 2. Select "Raspberry Pi OS (64-bit, Bookworm)"
# 3. Flash to SD card
# 4. Boot Pi and open terminal
```

### Step 6.2: Install HoralScanner
```bash
ssh pi@raspberrypi.local
sudo bash -c "curl -sSL https://raw.githubusercontent.com/jose33bro/horaltscanner/main/setup_pi.sh | bash"
sudo reboot
```

### Step 6.3: Configure Serial Devices (Creality & TF-Luna)
```bash
# Identify which USB device is which:
lsusb
ls -l /dev/ttyUSB*

# Optionally, create stable aliases:
bash /home/pi/horaltscanner/software/scripts/configure_serial_devices.sh
```

### Step 6.4: Verify GPIO & Drivers
```bash
sudo systemctl status horalscanner
sudo journalctl -u horalscanner -n 50

# Test API:
curl http://localhost:5000/api/status
curl -X POST http://localhost:5000/api/laser/left -H "Content-Type: application/json" -d '{"state": true}'
```

---

## Phase 7: Calibration & Testing

### Step 7.1: Motor Homing
1. Open dashboard: `http://<pi-ip>:5000`
2. Click **"Home All"** button
   - Motors should move to endstops (should hear mechanical clicks/stops)
   - Positions should reset to (0, 0, 0)
3. Check `journalctl` for errors; if homing fails, verify endstop wiring

### Step 7.2: Camera Focus & Alignment
1. Navigate to **Cameras** section in dashboard
2. Click **"Test USB Camera"** or **"Test Pi Camera"**
3. Verify image appears and is in focus
4. Adjust camera height (Z-axis) until object below is sharp

### Step 7.3: LiDAR Calibration
1. Place **known reference object** (e.g., flat board) 300 mm below LiDAR
2. Navigate to **LiDAR** section in dashboard
3. Click **"Calibrate"** with distance = 300 mm
4. Verify offset is stored; re-read distance should match reference

### Step 7.4: Laser Alignment (Optional)
1. Power ON both lasers from dashboard
2. Visually verify red dots appear on object below
3. Both lasers should form a **triangle with camera for triangulation**

### Step 7.5: Test Scan
1. Place small object (e.g., cube) on rotating platform below camera/laser
2. Navigate to **Scan** section in dashboard
3. Click **"Start Scan"** (full rotation, ~1 minute)
4. Monitor `journalctl` for errors
5. Once complete, click **"Reconstruct Model"**
6. Download STL and inspect in MeshLab or Cura

---

## Phase 8: Final Assembly & Enclosure (Optional)

### Step 8.1: Cable Routing
1. Bundle all **power cables** together (separate from signal cables)
2. Route behind frame or in cable tray
3. Label all connectors with masking tape

### Step 8.2: Dust Cover (Optional)
1. 3D-print or fabricate **acrylic enclosure** around scanner
2. Ensure adequate **airflow** for cooling fan
3. Add **access panel** for USB connections and power

### Step 8.3: Documentation
1. Take **photos of your build** (top, side, detail views)
2. Record any **deviations from this guide** (custom parts, modifications)
3. Create **assembly log** with dates and part serial numbers

---

## Troubleshooting

| Issue | Cause | Solution |
|---|---|---|
| Motors don't move after homing | Unhomed axis | Run "Home All" first; check endstop wiring |
| Camera image is blurry | Focus issue | Adjust Z-axis height; verify USB camera is secured |
| LiDAR reads 0 mm | Connection issue | Check USB port; verify `/dev/ttyUSB*` exists; run `cat /dev/ttyUSBn` |
| Laser won't turn ON | GPIO wiring issue | Verify GPIO27/22 with `gpio readall`; check transistor |
| Service fails to start | Missing drivers | Run `sudo systemctl status horalscanner` and check logs |
| Creality board won't connect | Serial port issue | Check USB cable quality; verify baud rate in config |

---

## Safety Warnings

⚠️ **Laser Safety:**
- Do NOT look directly into laser beam
- Wear appropriate laser safety glasses when powering lasers
- Keep hand/objects away from rotating platform during scans

⚠️ **Electrical Safety:**
- 24V power can cause injury; insulate all exposed connections
- Verify polarity before powering Creality board
- Shut down Pi gracefully (`sudo shutdown -h now`) before disconnecting power

⚠️ **Moving Parts:**
- Keep hair/loose clothing away from motors and ball screws
- Test movement with hand near limit before full motion
- Always verify endstops are installed before homing

---

## Version History

| Date | Version | Changes |
|---|---|---|
| 2026-08-29 | 1.0.0 | Initial assembly guide with Creality Hyper, PLA parts, GPIO wiring, calibration steps |


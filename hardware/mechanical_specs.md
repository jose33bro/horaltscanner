# HoralScanner — Mechanical Specifications

## Design Reference Frame

```
        Z-Axis (Height)
             ↑
             |
   Y-Axis ←--+--→ X-Axis (Rotation)
       (Forward/Back)
             
    Rear (Y=0) -------- Front (Y=100)
       ↑                    ↑
    Endstop         Object detection
```

---

## Ball Screw Specifications

### M5 × 40 Assembly (All Axes)

| Parameter | Value | Notes |
|---|---|---|
| **Thread Pitch** | M5 × 0.8 mm | ISO metric |
| **Ball Diameter** | Ø6.5 mm | Grade 25 hardened steel |
| **Ball Preload** | Light (1–2 N/mm²) | Reduces backlash to <0.1 mm |
| **Lead** | 5 mm/rev | 1 revolution = 5 mm travel |
| **Maximum Speed** | 20,000 steps/sec | Stepper limit (from motor_control.py) |
| **Max Linear Speed** | ~100 mm/sec | Calculated: 20k steps/sec ÷ 3200 steps/mm × 16 microsteps |
| **Preload Spring** | Light spring or adjustable collar | Rear bearing (fixed); front bearing (floating) |
| **Lubrication** | NLGI-2 lithium grease | Reapply every 500 hours of operation |

### Calculation: Steps per mm
```
Steps/mm = (200 steps/rev × 16 microsteps) / 5 mm pitch
         = 3200 / 5
         = 640 steps/mm
```

### Motion Limits

| Axis | Travel Range | Position Min | Position Max | Purpose |
|---|---|---|---|---|
| **X (Rotation)** | 0–360° | 0 mm | 360 mm | Continuous rotation platform |
| **Y (Forward/Back)** | 0–100 mm | 0 mm (rear, endstop) | 100 mm (front) | Linear scan axis |
| **Z (Height)** | 0–50 mm | 0 mm (+5 mm offset) | 50 mm | Camera height adjustment |

---

## 3D-Printed Parts (PLA)

### Camera Support Plate

**Overall Dimensions:**
```
   Front
      ↑
    7 mm (width)
      ↑
   ┌──────────────┐
   │  Socket      │ 1 mm (height/thickness)
   │   Ø6.9 mm    │ ← centered
   │  (centered)  │
   │    │││       │ ← 4 petal retainers (depth)
   └──┴─┴─┴──────┘
   28.05 mm (length)
```

**Key Specifications:**

| Feature | Dimension | Tolerance | Notes |
|---|---|---|---|
| **Length** | 28.05 mm | ±0.1 mm | Attachment footprint |
| **Width** | 7 mm | ±0.2 mm | Camera connector clearance |
| **Thickness** | 1 mm | ±0.2 mm | Minimal weight |
| **Socket Diameter** | Ø6.9 mm | ±0.05 mm | Logitech USB camera lens fit |
| **Socket Depth** | 4 mm | ±0.1 mm | Retainer petal depth |
| **Petal Retainers** | 4× radial petals | — | Grip camera housing without glue |
| **M3 Clearance Holes** | Ø3.2 mm | ±0.1 mm | Screw pass-through (not tapped) |
| **Hole Spacing** | 2× on 14 mm centers | ±0.2 mm | Frame attachment points |
| **Socket Centering** | Center ±0.1 mm | — | Optical axis alignment |

**Material Properties:**
- **Infill:** 15% grid pattern (sufficient for non-load-bearing bracket)
- **Layer Height:** 0.15 mm (for surface finish)
- **Support Material:** Breakaway supports on underside; clean before installation
- **Print Speed:** 60–80 mm/s (avoid warping at thin cross-section)
- **Bed Temp:** 60°C; Nozzle: 210°C

**Load Limits:**
- **Supported Mass:** <200 g (USB camera + lens)
- **Retention Force:** ~5 N (petal friction)
- **Failure Mode:** Petal cracking under excessive insertion torque

---

### Base Plate

**Overall Dimensions:**
```
    M5 Hole
      ↓ (Rear side)
    ┌────────────────────────┐
    │                        │
    │      BASE PLATE        │  Vertical offset: +5 mm
    │      (PLA)             │  from origin (Y=0, Z=0 ref)
    │                        │
    └─────────────────────────┘
      Rear (Y=0) ←→ Front (Y=100)
```

**Key Specifications:**

| Feature | Specification | Tolerance | Notes |
|---|---|---|---|
| **Length** | 100 mm | ±1 mm | Full Y-axis travel |
| **Width** | 50 mm | ±1 mm | Z-axis carriage mount |
| **Thickness** | 3 mm | ±0.2 mm | Structural rigidity |
| **M5 Tapped Hole** | M5 × 0.8 ISO | ±0.1 mm | Ball screw mounting (Z-axis) |
| **Hole Position** | Center rear, 10 mm from edge | ±0.5 mm | — |
| **Hole Type** | Tapped (M5×0.8) or threaded insert | — | Must support axial load of ball screw |
| **Vertical Offset Reference** | +5 mm above absolute origin | ±0.5 mm | **Calibration height** for TF-Luna Y-sync |
| **Orientation Marking** | "Rear → Front" engraved or labeled | — | Assembly guide |
| **Surface Finish** | Smooth (post-processed if needed) | — | Reduce friction on Y-carriage |

**Material Properties:**
- **Infill:** 25% (load-bearing structural part)
- **Layer Height:** 0.2 mm (strength > finish)
- **Support Material:** None (print with flat base down)
- **Print Speed:** 50–60 mm/s (ensure dimensional accuracy)
- **Bed Temp:** 60°C; Nozzle: 210°C

**Load Limits:**
- **Supported Mass:** <500 g (full scanner head + camera + laser)
- **M5 Thread Tensile Strength:** ~2 kN (PLA nominal)
- **Deflection:** <0.5 mm under full load (measure with dial indicator)

**Mounting to Frame:**
- Secure to Z-carriage with M3 fasteners (2× clearance holes if present)
- Use M3 nylon washers under screw heads to reduce PLA stress concentration
- Apply loctite (medium strength) to M5 ball screw socket

---

## Critical Dimensions & Calibration

### Camera Support Plate → Z-Carriage Interface

**Assembly Sequence:**

1. **Mount plate on Z-carriage:**
   - Position: Centered on carriage, front face (toward object)
   - Height: Flush with carriage top surface
   - Fasteners: M3×10 pan-head screws, 1.5–2 N·m torque

2. **Insert camera into socket:**
   - Logitech USB camera lens first (Ø6.9 mm)
   - Push gently until 4 petals engage connector housing
   - Verify horizontal (spirit level)
   - Do NOT force (risk breaking petals)

3. **Cable routing:**
   - USB cable exits toward rear
   - 100 mm slack for Y-motion
   - Cable tie at rear frame

**Clearance Check:**
- **Plate to ball screw:** 1 mm minimum (avoid binding during Z travel)
- **Socket to camera:** 0 mm (tight fit is intentional; creates retention)
- **Camera lens to object:** 50–200 mm working distance

---

### Base Plate → Frame Interface

**M5 Tapped Hole (Ball Screw Mounting):**

1. **Prepare hole:**
   - Clean PLA threads of any residual plastic
   - Test-thread M5 machine screw (should turn smoothly, no crunching)
   - If threads damaged, drill out Ø5.5 mm and install **M5 threaded insert** (helicoil type)

2. **Install ball screw:**
   - Thread M5×40 ball screw into tapped hole
   - Screw in until **slight resistance** (ball nut engagement)
   - Rotate screw manually: should turn **freely with light resistance**
   - If stuck: back out and apply light grease to threads

3. **Secure with lock nut:**
   - Thread M5 lock nut onto exposed ball screw
   - Torque: 10–15 N·m (prevents axial motion but allows rotation)
   - Verify screw doesn't rotate when nut is tightened

**Vertical Offset Calibration (+5 mm):**
- Measure Z-position of base plate **relative to its lowest position**
- When Z-axis is fully retracted, base plate should be **5 mm above origin**
- This ensures TF-Luna (mounted on Y-carriage) can measure object at optimal distance (50–100 mm)
- **Do NOT change this offset** without recalibrating `lidar_driver.py` offset constant

---

## Endstop Configuration

### Y-Axis Endstop (Rear Limit, Y=0)

**Mechanical:**
- **Type:** Microswitch, normally-open (NO), lever-activated
- **Mounting:** Fixed to rear frame or carriage rail
- **Activation Point:** Y-carriage contacts lever exactly at Y=0
- **Travel Distance to Stop:** <2 mm (minimal over-travel)

**Electrical:**
- **Wiring:** Common pin → GND; NO pin → Creality endstop input
- **Pull-up:** Enabled in Creality firmware (internal 10k resistor)
- **Logic:** Active LOW (switch closes = GND signal)

**Calibration:**
1. Jog Y-axis toward rear manually using dashboard
2. When carriage contacts endstop, listen for **click** from microswitch
3. In `motor_control.py`, set `home_offset_y = 0`
4. Run `api/home/y` endpoint; verify position resets to 0.0

---

## Electrical Connector Specifications

### Stepper Motor Connectors

**Wiring (4-wire, bipolar NEMA 17):**
```
Pin 1: Coil A+  (Red)
Pin 2: Coil A-  (Green)
Pin 3: Coil B+  (Blue)
Pin 4: Coil B-  (Black)

Creality V4.2.2 Motor Header Layout:
┌──────────┐
│ 1  2  3  4 │  (Typical: GND, STEP, DIR, +V)
│ GND STP DIR +V│
└──────────┘
```

**Cable Specifications:**
- **Type:** 4-conductor shielded cable (UTP acceptable for short runs)
- **AWG:** 22–26 gauge (1 m runs acceptable)
- **Connector:** Dupont 2.54mm female headers or equivalent
- **Length:** <1 m (minimize noise coupling)

---

## Tolerance & Fit Summary

| Component | Critical Tolerance | Rationale |
|---|---|---|
| **Camera Socket (Ø6.9)** | ±0.05 mm | Optical axis alignment (±0.1 mm lateral error acceptable) |
| **Ball Screw Hole (M5)** | ±0.1 mm | Thread engagement; prevent loosening |
| **M3 Fastener Holes** | ±0.2 mm | Clearance holes (not critical) |
| **Petal Depth (4 mm)** | ±0.1 mm | Retention force (too shallow = camera falls out) |
| **Vertical Offset (+5 mm)** | ±0.5 mm | LiDAR range calibration (software compensates) |
| **Base Plate Length (100 mm)** | ±1 mm | Non-critical (travel programmatically limited) |

---

## Testing & Verification Checklist

- [ ] Ball screws rotate freely by hand (all three axes)
- [ ] Camera plate is level (spirit level check)
- [ ] Socket Ø6.9 grips camera without excessive force
- [ ] M5 tapped hole threads cleanly (test with machine screw)
- [ ] Endstop activates at exactly Y=0 (measure with caliper)
- [ ] Motor homing completes successfully (check dashboard)
- [ ] LiDAR reads stable distances at various heights (100–300 mm range)
- [ ] Camera focus is sharp at intended working distance
- [ ] No binding or grinding sounds during axis motion
- [ ] USB camera frame rate stable (30 fps minimum)

---

## Version History

| Date | Version | Changes |
|---|---|---|
| 2026-08-29 | 1.0.0 | Initial mechanical specs: ball screws, PLA parts, tolerances, calibration procedure |


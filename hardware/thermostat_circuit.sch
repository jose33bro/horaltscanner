EESchema Schematic File Version 4
EELAYER 30 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 1 1
Title "Horaltscanner - Circuit Thermostat NTC 100K"
Date "2024-01-01"
Rev "1.0"
Comp "Horaltscanner Project"
Comment1 "Sonde température NTC 100K sur broche PA0 (ADC0) Creality V4.2.2"
Comment2 "Résistance pull-up 4.7K Ohm - Tension 3.3V"
Comment3 "Plage mesure: 0°C à 100°C"
Comment4 ""
$EndDescr
$Comp
L Device:R R1
U 1 1 5F3A1234
P 3500 3000
F 0 "R1" H 3570 3046 50  0000 L CNN
F 1 "4.7K" H 3570 2955 50  0000 L CNN
F 2 "" H 3500 3000 50  0001 C CNN
F 3 "~" H 3500 3000 50  0001 C CNN
	1    3500 3000
	1    0    0    -1  
$EndComp
$Comp
L Device:Thermistor_NTC TH1
U 1 1 5F3A5678
P 3500 3600
F 0 "TH1" H 3600 3650 50  0000 L CNN
F 1 "NTC 100K" H 3600 3550 50  0000 L CNN
F 2 "" H 3500 3600 50  0001 C CNN
F 3 "~" H 3500 3600 50  0001 C CNN
	1    3500 3600
	1    0    0    -1  
$EndComp
Wire Wire Line
	3500 2700 3500 2850
Wire Wire Line
	3500 3150 3500 3300
Wire Wire Line
	3500 3150 4200 3150
Wire Wire Line
	3500 3750 3500 3900
$Comp
L power:+3.3V #PWR01
U 1 1 5F3A9012
P 3500 2700
F 0 "#PWR01" H 3500 2550 50  0001 C CNN
F 1 "+3.3V" H 3515 2873 50  0000 C CNN
F 2 "" H 3500 2700 50  0001 C CNN
F 3 "" H 3500 2700 50  0001 C CNN
	1    3500 2700
	1    0    0    -1  
$EndComp
$Comp
L power:GND #PWR02
U 1 1 5F3AC345
P 3500 3900
F 0 "#PWR02" H 3500 3650 50  0001 C CNN
F 1 "GND" H 3505 3727 50  0000 C CNN
F 2 "" H 3500 3900 50  0001 C CNN
F 3 "" H 3500 3900 50  0001 C CNN
	1    3500 3900
	1    0    0    -1  
$EndComp
$Comp
L Connector:Conn_01x03_Male J1
U 1 1 5F3AF678
P 5000 3050
F 0 "J1" H 5108 3331 50  0000 C CNN
F 1 "PA0_ADC0_Creality" H 5108 3240 50  0000 C CNN
F 2 "" H 5000 3050 50  0001 C CNN
F 3 "~" H 5000 3050 50  0001 C CNN
	1    5000 3050
	1    0    0    -1  
$EndComp
Wire Wire Line
	4200 3150 5200 3150
Text Label 4200 3150 0 50  ~ 0
PA0_ADC0
Text Notes 2000 2500 0    50   ~ 0
Thermostat NTC 100K pour Creality V4.2.2\nBroche PA0 (ADC0) - Résistance pull-up 4.7K\nTension: 3.3V - Plage: 0-100°C
$EndSCHEMATC

/* Linker script pour STM32F103RB (Creality V4.2.2) */
/* Flash: 128KB (0x08000000 - 0x0801FFFF) */
/* RAM: 20KB (0x20000000 - 0x20004FFF) */

MEMORY
{
    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 128K
    RAM (rwx)  : ORIGIN = 0x20000000, LENGTH = 20K
}

SECTIONS
{
    .text :
    {
        KEEP(*(.vectors))
        *(.text)
        *(.text*)
        *(.rodata)
        *(.rodata*)
    } > FLASH
    
    .data :
    {
        *(.data)
        *(.data*)
    } > RAM AT > FLASH
    
    .bss :
    {
        *(.bss)
        *(.bss*)
        *(COMMON)
    } > RAM
    
    .stab 0 (NOLOAD) :
    {
        [ .stab ]
    }
    
    .stabstr 0 (NOLOAD) :
    {
        [ .stabstr ]
    }
}

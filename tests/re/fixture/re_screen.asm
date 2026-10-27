; A target that writes a known character to the text screen, then loops.
bits 16
org 100h

start:
    mov ax, 0xB800
    mov es, ax
    mov word [es:0], 0x1F41   ; 'A' on the first row
    mov word [es:160], 0x1F42 ; 'B' on the second row
loop_here:
    jmp loop_here

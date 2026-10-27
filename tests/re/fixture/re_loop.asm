; A target that sets the registers and loops, for the agent method tests.
bits 16
org 100h

start:
    mov ax, 0x1234
    mov bx, 0x5678
loop_here:
    jmp loop_here

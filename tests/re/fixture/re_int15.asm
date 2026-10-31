; A target that calls the DOS/4GW INT 15h services and records the answers.
; The record lives at 0x2000:0x300, so the test reads a fixed address.
bits 16
org 100h

start:
    mov ax, 0x2000
    mov es, ax

    mov ax, 0xBFDE
    mov bx, 0x000A
    int 0x15
    mov [es:0x0300], ax

    mov word [es:0x000A], 0xDEAD
    mov word [es:0x000C], 0xBEEF
    mov ax, 0xBFDE
    mov bx, 0x0015
    mov cx, 0x0005
    int 0x15
    mov [es:0x0304], ax
    mov ax, [es:0x000A]
    mov [es:0x0306], ax
    mov ax, [es:0x000C]
    mov [es:0x0308], ax
    mov [es:0x030A], cs

    mov ax, 0xBFDE
    mov bx, 0x0000
    int 0x15
    mov [es:0x030C], ax

loop_here:
    jmp loop_here

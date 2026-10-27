; A small DOS program for the fork tests.
;
; It writes a known byte at a known address in its data segment, calls the
; DOS version service with AH=30, and loops at a known address.
bits 16
org 100h

start:
    mov ax, 0x1234
    mov bx, 0x5678
    mov si, 0x0200
    mov byte [si], 0x41
    mov word [si + 1], 0x4243
    mov ah, 0x30
    int 0x21
loop_here:
    jmp loop_here

; A target that opens, reads, and closes a file, then loops.
bits 16
org 100h

start:
    mov dx, filename
    mov ax, 0x3D00
    int 0x21
    jc loop_here
    mov bx, ax
    mov cx, 8
    mov dx, buffer
    mov ah, 0x3F
    int 0x21
    mov ah, 0x3E
    int 0x21
loop_here:
    jmp loop_here

filename db "REFIO.COM", 0
buffer times 8 db 0

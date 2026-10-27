; A target that records the injected key and the mouse state.
; The record lives at 0x2000:0x300, so the test reads a fixed address.
; The key record sits at 0x300, the button at 0x304, the x at 0x306, and
; the y at 0x308.  The poll axis sits at 0x30c.
bits 16
org 100h

start:
    mov ax, 0x2000
    mov es, ax
    xor ax, ax
    int 0x33          ; reset the mouse driver
loop_here:
    mov ax, 3
    int 0x33           ; BX = the buttons, CX = x, DX = y
    mov [es:0x30c], ax  ; record the poll axis
    test bl, 1
    jz no_button
    mov byte [es:0x304], 1
    mov [es:0x306], cx
    mov [es:0x308], dx
no_button:
    mov ah, 1
    int 0x16           ; check a key
    jz no_key
    mov ah, 0
    int 0x16           ; read the key
    mov [es:0x300], al
no_key:
    jmp loop_here

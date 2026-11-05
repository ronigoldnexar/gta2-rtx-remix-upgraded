# The block at the start of this DLL's code that covers base + 0x485E0, where
# plugins written for the original renderer look for a pointer to its state.
# See plugin_d3d6.cpp, and plugin_slot.asm for the MSVC build.
#
# GNU ld lays the plain .text input sections out in command-line order and the
# .text$* ones after them, so this object is placed in plain .text and listed
# first on the link line: then only the DLL's startup stub precedes it, and the
# block covers 0x485E0. The size is kReservedBytes in plugin_d3d6.cpp.
    .text
    .globl _g_reservedForRendererState
_g_reservedForRendererState:
    .space 0x49000, 0

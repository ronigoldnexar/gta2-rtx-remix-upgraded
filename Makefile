# Builds gta2dx9.dll and gta2dx9_vid.dll on Linux (or macOS) with the MinGW-w64
# cross compiler, and stages the files a player drops into the GTA2 folder.
#
#   make            both DLLs into dll/build and vid/build, staged in stage/
#   make check      ... and loads them under Wine to prove every export resolves
#   make clean
#
# Needs: g++-mingw-w64-i686 (Debian/Ubuntu), mingw64-gcc-c++ (Fedora, i686
# target), mingw-w64-gcc (Arch). The Windows build is still dll\build.bat and
# vid\build.bat with Visual Studio; both produce the same DLLs.

# The cross toolchain prefix. Not CXX/CC from the environment: those name the
# host compiler, which has no windows.h.
CROSS   ?= i686-w64-mingw32-
CXX     := $(CROSS)g++
CC      := $(CROSS)gcc
WINE    ?= wine

CXXFLAGS := -std=c++17 -O2 -w -DNOMINMAX -D_CRT_SECURE_NO_WARNINGS -DUNICODE_DISABLED \
            -Idll/deps/bridge_api -Idll/deps/imgui -fno-strict-aliasing
# Static runtime: the DLL must not depend on a libstdc++ or libgcc DLL that is
# not beside gta2.exe. --kill-at exports the __stdcall names undecorated, which is
# what gta2.exe asks GetProcAddress for; the .def files add ordinals.
LDFLAGS  := -shared -static -static-libgcc -static-libstdc++ -Wl,--kill-at -Wl,--enable-stdcall-fixup
DLL_LIBS := -luser32 -lpsapi -lgdi32 -ldwmapi -lwinmm -lole32 -lshell32 -ladvapi32 -luuid
VID_LIBS := -luser32

DLL_SRC := $(wildcard dll/src/*.cpp) $(wildcard src/*.cpp) \
           dll/deps/imgui/imgui.cpp dll/deps/imgui/imgui_draw.cpp dll/deps/imgui/imgui_tables.cpp \
           dll/deps/imgui/imgui_widgets.cpp dll/deps/imgui/backends/imgui_impl_dx9.cpp \
           dll/deps/imgui/backends/imgui_impl_win32.cpp
DLL_OBJ := $(patsubst %.cpp,dll/build/obj/%.o,$(DLL_SRC))
# First on the link line on purpose: see dll/src/plugin_slot.S.
SLOT_OBJ := dll/build/obj/plugin_slot.o

all: stage

dll/build/obj/%.o: %.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -c -o $@ $<

$(SLOT_OBJ): dll/src/plugin_slot.S
	@mkdir -p $(dir $@)
	$(CC) -c -o $@ $<

dll/build/gta2dx9.dll: $(SLOT_OBJ) $(DLL_OBJ) dll/gta2dx9.def
	$(CXX) $(LDFLAGS) -o $@ $(SLOT_OBJ) $(DLL_OBJ) dll/gta2dx9.def $(DLL_LIBS)

vid/build/gta2dx9_vid.dll: vid/src/vid_proxy.cpp vid/dmavideo.def
	@mkdir -p vid/build
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ vid/src/vid_proxy.cpp vid/dmavideo.def $(VID_LIBS)

stage: dll/build/gta2dx9.dll vid/build/gta2dx9_vid.dll
	@mkdir -p stage
	cp dll/build/gta2dx9.dll stage/gta2dx9.dll
	cp dll/build/gta2dx9.dll stage/d3ddll.dll
	cp vid/build/gta2dx9_vid.dll stage/gta2dx9_vid.dll
	cp vid/build/gta2dx9_vid.dll stage/Dmavideo.dll
	cp vid/build/gta2dx9_vid.dll stage/DMAGlide.dll
	cp package/gta2dx9.ini package/install.reg package/uninstall.reg stage/
	@echo "Staged in stage/: unzip-equivalent of the release, see linux/README.md"

# Loads both DLLs under Wine and resolves every export GTA2 asks for. See
# linux/loadcheck.cpp. Needs wine (32-bit support) on the PATH.
linux/build/loadcheck.exe: linux/loadcheck.cpp dll/src/gbh_exports.h
	@mkdir -p linux/build
	$(CXX) -std=c++17 -O1 -Idll/src -o $@ $< -static

check: stage linux/build/loadcheck.exe
	cd stage && $(WINE) ../linux/build/loadcheck.exe

clean:
	rm -rf dll/build vid/build stage linux/build

.PHONY: all stage check clean

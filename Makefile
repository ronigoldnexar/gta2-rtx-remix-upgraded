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

# -MMD: a header change rebuilds every object that includes it. Without this a
# class that gains a member is laid out one way in the object that was rebuilt
# and another in the objects that were not, and the DLL corrupts its own
# globals at run time.
dll/build/obj/%.o: %.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -MMD -MP -c -o $@ $<
-include $(DLL_OBJ:.o=.d)

$(SLOT_OBJ): dll/src/plugin_slot.S
	@mkdir -p $(dir $@)
	$(CC) -c -o $@ $<

# -Map: dll/build/gta2dx9.map names every function's address, so a crash offset in the
# log (gta2dx9.dll+0x...) can be looked up; staged beside the DLL (FIX-STABILITY-1).
dll/build/gta2dx9.dll: $(SLOT_OBJ) $(DLL_OBJ) dll/gta2dx9.def
	$(CXX) $(LDFLAGS) -Wl,-Map,dll/build/gta2dx9.map -o $@ $(SLOT_OBJ) $(DLL_OBJ) dll/gta2dx9.def $(DLL_LIBS)

vid/build/gta2dx9_vid.dll: vid/src/vid_proxy.cpp vid/dmavideo.def
	@mkdir -p vid/build
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ vid/src/vid_proxy.cpp vid/dmavideo.def $(VID_LIBS)

stage: dll/build/gta2dx9.dll vid/build/gta2dx9_vid.dll
	@mkdir -p stage
	cp dll/build/gta2dx9.dll stage/gta2dx9.dll
	cp dll/build/gta2dx9.dll stage/d3ddll.dll
	cp dll/build/gta2dx9.map stage/gta2dx9.map
	cp vid/build/gta2dx9_vid.dll stage/gta2dx9_vid.dll
	cp vid/build/gta2dx9_vid.dll stage/Dmavideo.dll
	cp vid/build/gta2dx9_vid.dll stage/DMAGlide.dll
	cp package/gta2dx9.ini package/gta2dx9_effects.ini package/install.reg package/uninstall.reg stage/
	rm -rf stage/gta2dx9_models && cp -r assets/models stage/gta2dx9_models
	# High-resolution tiles, when they have been generated (tools/upscale_textures.py; not in git, 400 MB).
	rm -rf stage/gta2dx9_textures_hd; if [ -d assets/textures_hd ]; then cp -r assets/textures_hd stage/gta2dx9_textures_hd; fi
	# DISTRICTS facade kit: regenerated here from the map, deterministically, never committed (docs/districts-plan.md).
	# Only with DISTRICTS_DATA=<game data dir> (and DISTRICTS_PY=<python with numpy+Pillow>); DISTRICTS_MODE=all for every building.
	rm -rf stage/gta2dx9_districts; if [ -n "$(DISTRICTS_DATA)" ]; then bash tools/districts/build_kits.sh "$(DISTRICTS_DATA)" assets/textures_hd stage/gta2dx9_districts $(or $(DISTRICTS_MODE),poc); fi
	@echo "Staged in stage/: unzip-equivalent of the release, see linux/README.md"

# Loads both DLLs under Wine and resolves every export GTA2 asks for. See
# linux/loadcheck.cpp. Needs wine (32-bit support) on the PATH.
linux/build/loadcheck.exe: linux/loadcheck.cpp dll/src/gbh_exports.h
	@mkdir -p linux/build
	$(CXX) -std=c++17 -O1 -Idll/src -o $@ $< -static

linux/build/sehcheck.exe: linux/sehcheck.cpp dll/src/compat.cpp dll/src/compat.h
	@mkdir -p linux/build
	$(CXX) -std=c++17 -O2 -Idll/src -o $@ linux/sehcheck.cpp dll/src/compat.cpp -static

check: stage linux/build/loadcheck.exe linux/build/sehcheck.exe
	python3 tools/check_ini_sections.py package/gta2dx9.ini
	@if command -v $(WINE) >/dev/null 2>&1; then \
	  ( cd stage && $(WINE) ../linux/build/loadcheck.exe ) && $(WINE) linux/build/sehcheck.exe; \
	else \
	  echo "SKIP: load check and SEH check need Wine ('$(WINE)' not on PATH); both tools linked, ini check ran"; \
	fi

# FIX-PERF-6: the large-address-aware step for a player's gta2.exe (tools/laa/gta2dx9_laa.cpp). Prepared for
# the release, not staged and not packed: shipping it is the owner's decision (docs/stability.md).
laa-tool: linux/build/gta2dx9_laa.exe
linux/build/gta2dx9_laa.exe: tools/laa/gta2dx9_laa.cpp
	@mkdir -p linux/build
	$(CXX) -std=c++17 -O2 -o $@ $< -static

clean:
	rm -rf dll/build vid/build stage linux/build

.PHONY: all stage check clean laa-tool

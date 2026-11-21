PAK_NAME ?= $(shell jq -r .name pak.json 2>/dev/null || echo N64Bench)
PLATFORMS ?= tg5040 tg5050 h700

NEXTUI_REPO ?= /var/home/pobega/Code/NextUI
NEXTUI_COMMIT ?= 32626b02d9f95d7cc377cabc858d94ff713ff416

REARMED_PAK_DIR ?= /var/home/pobega/Code/nextui-mupen64plus-rearmed-pak
PARALLEL_PAK_DIR ?= /var/home/pobega/Code/nextui-parallel-n64-pak

CONTAINER_RUNTIME ?= $(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null || (command -v flatpak-spawn >/dev/null 2>&1 && echo "flatpak-spawn --host podman"))
ifeq (,$(CONTAINER_RUNTIME))
$(error Neither docker nor podman found in PATH)
endif

ifneq (,$(findstring podman,$(CONTAINER_RUNTIME)))
CONTAINER_MOUNT_OPTS ?= --security-opt label=disable
else
CONTAINER_MOUNT_OPTS ?=
endif

PUSH_PLATFORM ?= h700
PUSH_SDCARD_PATH ?= /mnt/SDCARD

BUILD_DIR := $(CURDIR)/build
NEXTUI_SRC := $(BUILD_DIR)/NextUI
BIN_DIR := $(BUILD_DIR)/bin
CORES_DIR := $(BUILD_DIR)/cores
DIST_DIR := $(CURDIR)/dist

.PHONY: all src-nextui build-minarch build-benchctl build-cores build package release push clean distclean \
	$(foreach p,$(PLATFORMS),minarch-$(p) benchctl-$(p) cores-$(p))

all: release

src-nextui: $(NEXTUI_SRC)/.patched

$(NEXTUI_SRC)/.patched: $(wildcard $(CURDIR)/patches/*.patch)
	@mkdir -p $(BUILD_DIR)
	@if [ ! -d "$(NEXTUI_SRC)/.git" ]; then \
		echo "Cloning NextUI from $(NEXTUI_REPO)..."; \
		git clone --no-hardlinks $(NEXTUI_REPO) $(NEXTUI_SRC); \
	fi
	@git -C $(NEXTUI_SRC) reset --hard -q $(NEXTUI_COMMIT)
	@git -C $(NEXTUI_SRC) clean -fdq workspace/all/minarch/ma_bench.*
	@echo "$(NEXTUI_COMMIT)" | cut -c1-8 > $(NEXTUI_SRC)/workspace/hash.txt
	@for d in libretro-common rcheevos libchdr; do \
		if [ ! -d "$(NEXTUI_SRC)/workspace/all/minarch/$$d" ] && [ -d "$(NEXTUI_REPO)/workspace/all/minarch/$$d" ]; then \
			cp -a "$(NEXTUI_REPO)/workspace/all/minarch/$$d" "$(NEXTUI_SRC)/workspace/all/minarch/$$d"; \
		fi; \
	done
	@for p in $(CURDIR)/patches/*.patch; do \
		[ -f "$$p" ] || continue; \
		if git -C $(NEXTUI_SRC) apply -R --check "$$p" >/dev/null 2>&1; then \
			echo "Patch $$(basename "$$p") already applied"; \
		elif git -C $(NEXTUI_SRC) apply --check "$$p" >/dev/null 2>&1; then \
			echo "Applying patch $$(basename "$$p")"; \
			git -C $(NEXTUI_SRC) apply "$$p"; \
		else \
			echo "Error: Failed to apply patch $$p"; exit 1; \
		fi; \
	done
	@touch $(NEXTUI_SRC)/.patched

define BUILD_PLATFORM_RULES
minarch-$(1): src-nextui
	@echo "Building minarch-bench.elf for $(1)..."
	@mkdir -p $(BIN_DIR)/$(1)
	$$(CONTAINER_RUNTIME) run --rm $$(CONTAINER_MOUNT_OPTS) \
		-v $(NEXTUI_SRC)/workspace:/root/workspace:rw \
		ghcr.io/loveretro/$(1)-toolchain:latest \
		bash -euc 'cd /root/workspace/all/minarch && make PLATFORM=$(1)'
	@cp $(NEXTUI_SRC)/workspace/all/minarch/build/$(1)/minarch.elf $(BIN_DIR)/$(1)/minarch-bench.elf
	@chmod 0755 $(BIN_DIR)/$(1)/minarch-bench.elf

benchctl-$(1): src/benchctl.c
	@echo "Building benchctl for $(1)..."
	@mkdir -p $(BIN_DIR)/$(1)
	$$(CONTAINER_RUNTIME) run --rm $$(CONTAINER_MOUNT_OPTS) \
		-v $$(CURDIR):/workspace:rw \
		ghcr.io/loveretro/$(1)-toolchain:latest \
		bash -euc '\
			/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-gcc -std=c99 -O2 -Wall -Wextra -Werror \
				/workspace/src/benchctl.c -o /workspace/build/bin/$(1)/benchctl && \
			/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-strip --strip-unneeded /workspace/build/bin/$(1)/benchctl && \
			chmod 0755 /workspace/build/bin/$(1)/benchctl \
		'

cores-$(1):
	@echo "Gathering/building N64 cores for $(1)..."
	@mkdir -p $(CORES_DIR)/$(1)
	@if [ "$(1)" = "tg5050" ]; then \
		$(MAKE) -C $(REARMED_PAK_DIR) src; \
		$(MAKE) -C $(PARALLEL_PAK_DIR) src; \
		$$(CONTAINER_RUNTIME) run --rm $$(CONTAINER_MOUNT_OPTS) \
			-v $(REARMED_PAK_DIR):/src-rearmed:rw \
			-v $(PARALLEL_PAK_DIR):/src-parallel:rw \
			-v $$(CURDIR):/workspace:rw \
			ghcr.io/loveretro/tg5050-toolchain:latest \
			bash -euc '\
				mkdir -p /tmp/khr-inc/KHR /tmp/khr-inc/EGL && \
				ln -sf /opt/aarch64-nextui-linux-gnu/aarch64-nextui-linux-gnu/libc/usr/include/SDL2/SDL_opengles2_khrplatform.h /tmp/khr-inc/KHR/khrplatform.h && \
				touch /tmp/khr-inc/EGL/egl.h && \
				export CFLAGS="-mcpu=cortex-a55 -mtune=cortex-a55 -I/tmp/khr-inc" && \
				export CXXFLAGS="-mcpu=cortex-a55 -mtune=cortex-a55 -I/tmp/khr-inc" && \
				export LDFLAGS="-mcpu=cortex-a55 -mtune=cortex-a55" && \
				cd /src-rearmed/build/mupen64plus-rearmed && \
				rm -f mupen64plus_rearmed_libretro.so && find . \( -name "*.o" -o -name "*.d" \) -delete && \
				make -j$$$$(nproc) platform=unix ARCH=aarch64 WITH_DYNAREC=aarch64 GLES=1 \
					GL_LIB="-lGLESv2 -lmali" \
					HAVE_PARALLEL=0 HAVE_PARALLEL_RSP=0 HAVE_GLIDEN64=0 HAVE_THR_AL=0 HAVE_GLIDE64=1 HAVE_RICE=1 HAVE_GLN64=1 \
					CC=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-gcc \
					CXX=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-g++ \
					AR=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-ar \
					CC_AS=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-gcc && \
				cp mupen64plus_rearmed_libretro.so /workspace/build/cores/tg5050/mupen64plus_rearmed_libretro.so && \
				/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-strip --strip-unneeded /workspace/build/cores/tg5050/mupen64plus_rearmed_libretro.so && \
				cd /src-parallel/build/parallel-n64 && \
				rm -f parallel_n64_libretro.so && find . \( -name "*.o" -o -name "*.d" \) -delete && \
				make -j$$$$(nproc) platform=unix ARCH=aarch64 WITH_DYNAREC=aarch64 GLES=1 \
					GL_LIB="-lGLESv2 -lmali" \
					HAVE_PARALLEL=0 HAVE_PARALLEL_RSP=0 HAVE_GLIDEN64=0 HAVE_GLN64=0 HAVE_THR_AL=0 HAVE_GLIDE64=1 HAVE_RICE=1 \
					CC=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-gcc \
					CXX=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-g++ \
					AR=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-ar \
					CC_AS=/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-gcc && \
				cp parallel_n64_libretro.so /workspace/build/cores/tg5050/parallel_n64_libretro.so && \
				/opt/aarch64-nextui-linux-gnu/bin/aarch64-nextui-linux-gnu-strip --strip-unneeded /workspace/build/cores/tg5050/parallel_n64_libretro.so \
			'; \
	else \
		if [ ! -f "$(REARMED_PAK_DIR)/build/cores/$(1)/mupen64plus_rearmed_libretro.so" ]; then \
			$(MAKE) -C $(REARMED_PAK_DIR) PLATFORMS="$(1)" build-$(1); \
		fi; \
		cp "$(REARMED_PAK_DIR)/build/cores/$(1)/mupen64plus_rearmed_libretro.so" "$(CORES_DIR)/$(1)/"; \
		if [ ! -f "$(PARALLEL_PAK_DIR)/build/cores/$(1)/parallel_n64_libretro.so" ]; then \
			$(MAKE) -C $(PARALLEL_PAK_DIR) PLATFORMS="$(1)" build-$(1); \
		fi; \
		cp "$(PARALLEL_PAK_DIR)/build/cores/$(1)/parallel_n64_libretro.so" "$(CORES_DIR)/$(1)/"; \
	fi
	@chmod 0755 $(CORES_DIR)/$(1)/*.so
endef

$(foreach p,$(PLATFORMS),$(eval $(call BUILD_PLATFORM_RULES,$(p))))

build-minarch: $(foreach p,$(PLATFORMS),minarch-$(p))
build-benchctl: $(foreach p,$(PLATFORMS),benchctl-$(p))
build-cores: $(foreach p,$(PLATFORMS),cores-$(p))
build: build-minarch build-benchctl build-cores

package:
	@echo "Packaging $(PAK_NAME).pak.zip and platform tool distributions..."
	@mkdir -p $(DIST_DIR)
	@rm -rf $(BUILD_DIR)/staging $(DIST_DIR)/$(PAK_NAME).pak.zip
	@mkdir -p $(BUILD_DIR)/staging/config $(BUILD_DIR)/staging/roms $(BUILD_DIR)/staging/states
	@cp pak.json launch.sh LICENSE README.md $(BUILD_DIR)/staging/
	@chmod 0755 $(BUILD_DIR)/staging/launch.sh
	@cp config/*.json $(BUILD_DIR)/staging/config/
	@cp roms/.gitkeep $(BUILD_DIR)/staging/roms/
	@cp states/.gitkeep $(BUILD_DIR)/staging/states/
	@for p in $(PLATFORMS); do \
		mkdir -p $(BUILD_DIR)/staging/bin/$$p $(BUILD_DIR)/staging/cores/$$p; \
		cp $(BIN_DIR)/$$p/minarch-bench.elf $(BIN_DIR)/$$p/benchctl $(BUILD_DIR)/staging/bin/$$p/; \
		cp $(CORES_DIR)/$$p/*.so $(BUILD_DIR)/staging/cores/$$p/; \
		chmod 0755 $(BUILD_DIR)/staging/bin/$$p/* $(BUILD_DIR)/staging/cores/$$p/*; \
		mkdir -p $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/bin/$$p $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/cores/$$p \
			$(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/config $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/roms $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/states; \
		cp pak.json launch.sh LICENSE README.md $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/; \
		chmod 0755 $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/launch.sh; \
		cp config/*.json $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/config/; \
		cp $(BIN_DIR)/$$p/minarch-bench.elf $(BIN_DIR)/$$p/benchctl $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/bin/$$p/; \
		cp $(CORES_DIR)/$$p/*.so $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/cores/$$p/; \
	done
	@cd $(BUILD_DIR)/staging && zip -r $(DIST_DIR)/$(PAK_NAME).pak.zip .
	@echo "Successfully packaged $(DIST_DIR)/$(PAK_NAME).pak.zip"

release: build package

push:
	adb push $(DIST_DIR)/Tools/$(PUSH_PLATFORM)/$(PAK_NAME).pak/. $(PUSH_SDCARD_PATH)/Tools/$(PUSH_PLATFORM)/$(PAK_NAME).pak

clean:
	rm -rf $(BIN_DIR) $(CORES_DIR) $(BUILD_DIR)/staging $(DIST_DIR)

distclean: clean
	rm -rf $(BUILD_DIR)

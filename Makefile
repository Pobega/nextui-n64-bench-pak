PAK_NAME ?= $(shell jq -r .name pak.json 2>/dev/null || echo N64Bench)
PLATFORMS ?= tg5040 tg5050 h700

MINUI_LIST_VERSION ?= 0.16.0
MINUI_PRESENTER_VERSION ?= 0.14.0

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

.PHONY: all src-nextui build-minarch build-benchctl build-ui build-cores build package states-pack release push clean distclean \
	$(foreach p,$(PLATFORMS),minarch-$(p) benchctl-$(p) ui-$(p) cores-$(p))

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

$(BIN_DIR)/%/minui-list:
	@mkdir -p $(dir $@)
	curl -f -sSL -o $@ https://github.com/josegonzalez/minui-list/releases/download/$(MINUI_LIST_VERSION)/minui-list-$*-nextui
	@chmod 0755 $@

$(BIN_DIR)/%/minui-presenter:
	@mkdir -p $(dir $@)
	curl -f -sSL -o $@ https://github.com/josegonzalez/minui-presenter/releases/download/$(MINUI_PRESENTER_VERSION)/minui-presenter-$*-nextui
	@chmod 0755 $@

define BUILD_PLATFORM_RULES
ui-$(1): $(BIN_DIR)/$(1)/minui-list $(BIN_DIR)/$(1)/minui-presenter

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
build-ui: $(foreach p,$(PLATFORMS),ui-$(p))
build-cores: $(foreach p,$(PLATFORMS),cores-$(p))
build: build-minarch build-benchctl build-ui build-cores

package:
	@echo "Packaging $(PAK_NAME).pak.zip, $(PAK_NAME)-manual.zip, and platform tool distributions..."
	@mkdir -p $(DIST_DIR)
	@rm -rf $(BUILD_DIR)/staging $(DIST_DIR)/$(PAK_NAME).pak.zip $(DIST_DIR)/$(PAK_NAME)-manual.zip $(DIST_DIR)/SHA256SUMS.txt
	@mkdir -p $(BUILD_DIR)/staging/$(PAK_NAME).pak/config $(BUILD_DIR)/staging/$(PAK_NAME).pak/roms $(BUILD_DIR)/staging/$(PAK_NAME).pak/states $(BUILD_DIR)/staging/$(PAK_NAME).pak/inputs
	@cp pak.json launch.sh LICENSE README.md $(BUILD_DIR)/staging/$(PAK_NAME).pak/
	@chmod 0755 $(BUILD_DIR)/staging/$(PAK_NAME).pak/launch.sh
	@cp config/*.json $(BUILD_DIR)/staging/$(PAK_NAME).pak/config/
	@cp roms/.gitkeep $(BUILD_DIR)/staging/$(PAK_NAME).pak/roms/
	@cp states/.gitkeep $(BUILD_DIR)/staging/$(PAK_NAME).pak/states/
	@cp inputs/.gitkeep $(BUILD_DIR)/staging/$(PAK_NAME).pak/inputs/
	@for f in inputs/*.inp; do [ -f "$$f" ] && cp "$$f" $(BUILD_DIR)/staging/$(PAK_NAME).pak/inputs/; done || true
	@for p in $(PLATFORMS); do \
		mkdir -p $(BUILD_DIR)/staging/$(PAK_NAME).pak/bin/$$p $(BUILD_DIR)/staging/$(PAK_NAME).pak/cores/$$p; \
		cp $(BIN_DIR)/$$p/minarch-bench.elf $(BIN_DIR)/$$p/benchctl $(BIN_DIR)/$$p/minui-list $(BIN_DIR)/$$p/minui-presenter $(BUILD_DIR)/staging/$(PAK_NAME).pak/bin/$$p/; \
		cp $(CORES_DIR)/$$p/*.so $(BUILD_DIR)/staging/$(PAK_NAME).pak/cores/$$p/; \
		chmod 0755 $(BUILD_DIR)/staging/$(PAK_NAME).pak/bin/$$p/* $(BUILD_DIR)/staging/$(PAK_NAME).pak/cores/$$p/*; \
		mkdir -p $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/bin/$$p $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/cores/$$p \
			$(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/config $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/roms $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/states \
			$(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/inputs; \
		cp pak.json launch.sh LICENSE README.md $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/; \
		chmod 0755 $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/launch.sh; \
		cp config/*.json $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/config/; \
		cp inputs/.gitkeep $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/inputs/; \
		for f in inputs/*.inp; do [ -f "$$f" ] && cp "$$f" $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/inputs/; done || true; \
		cp $(BIN_DIR)/$$p/minarch-bench.elf $(BIN_DIR)/$$p/benchctl $(BIN_DIR)/$$p/minui-list $(BIN_DIR)/$$p/minui-presenter $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/bin/$$p/; \
		cp $(CORES_DIR)/$$p/*.so $(DIST_DIR)/Tools/$$p/$(PAK_NAME).pak/cores/$$p/; \
	done
	@cd $(BUILD_DIR)/staging/$(PAK_NAME).pak && zip -r $(DIST_DIR)/$(PAK_NAME).pak.zip .
	@cd $(BUILD_DIR)/staging && zip -r $(DIST_DIR)/$(PAK_NAME)-manual.zip $(PAK_NAME).pak
	@cd $(DIST_DIR) && sha256sum $(PAK_NAME).pak.zip $(PAK_NAME)-manual.zip > SHA256SUMS.txt
	@echo "Successfully packaged $(DIST_DIR)/$(PAK_NAME).pak.zip and $(DIST_DIR)/$(PAK_NAME)-manual.zip"

states-pack:
	@mkdir -p $(DIST_DIR)
	@if ! ls states/*.st0 >/dev/null 2>&1; then \
		echo "No local states/*.st0 found; skipping n64bench-states.tar.gz."; \
	else \
		rm -f $(DIST_DIR)/n64bench-states.tar.gz; \
		tar -czf $(DIST_DIR)/n64bench-states.tar.gz states/*.st0; \
		echo "Successfully packed $(DIST_DIR)/n64bench-states.tar.gz"; \
	fi

release: build package

push:
	adb push $(DIST_DIR)/Tools/$(PUSH_PLATFORM)/$(PAK_NAME).pak/. $(PUSH_SDCARD_PATH)/Tools/$(PUSH_PLATFORM)/$(PAK_NAME).pak

clean:
	rm -rf $(BIN_DIR) $(CORES_DIR) $(BUILD_DIR)/staging $(DIST_DIR)

distclean: clean
	rm -rf $(BUILD_DIR)

#!/bin/sh

PAK_DIR="$(cd "$(dirname "$0")" && pwd)"
PAK_NAME="$(basename "$PAK_DIR" .pak)"

if [ "$PLATFORM" = "tg3040" ] && [ -z "$DEVICE" ]; then
	export DEVICE="brick"
	export PLATFORM="tg5040"
fi

if [ -n "$LOGS_PATH" ]; then
	mkdir -p "$LOGS_PATH"
	LOG_FILE="$LOGS_PATH/$PAK_NAME.txt"
	rm -f "$LOG_FILE"
	exec > "$LOG_FILE" 2>&1
fi

export PATH="$PAK_DIR/bin/$PLATFORM:$PATH"
chmod +x "$PAK_DIR/bin/$PLATFORM/"* 2>/dev/null || true

BENCHCTL="$PAK_DIR/bin/$PLATFORM/benchctl"
MINARCH_BENCH="$PAK_DIR/bin/$PLATFORM/minarch-bench.elf"
PROFILES_JSON="$PAK_DIR/config/profiles.json"
SCENARIOS_JSON="$PAK_DIR/config/scenarios.json"
PAK_JSON="$PAK_DIR/pak.json"
RESULTS_ROOT="$PAK_DIR/results"
LAST_SUMMARY_TXT="$RESULTS_ROOT/last_summary.txt"

WORK_DIR="/tmp/${PAK_NAME}-work"
MENU_JSON="$WORK_DIR/menu.json"
CHOICE_OUT="$WORK_DIR/choice.out"
SUB_JSON="$WORK_DIR/sub.json"
SUB_TSV="$WORK_DIR/sub.tsv"
SUB_OUT="$WORK_DIR/sub.out"
PLAN_TSV="$WORK_DIR/plan.tsv"
GEN_TSV="$WORK_DIR/genstate.tsv"
GEN_META="$WORK_DIR/genstate.meta"

TAB="$(printf '\t')"
MODE="both"
DEV_TAG="${DEVICE:-$PLATFORM}"

PAK_VERSION="unknown"
if [ -f "$PAK_JSON" ]; then
	parsed_ver="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$PAK_JSON" | head -n 1)"
	[ -n "$parsed_ver" ] && PAK_VERSION="$parsed_ver"
fi
export BENCH_PAK_VERSION="$PAK_VERSION"

mkdir -p "$WORK_DIR" "$RESULTS_ROOT" "${BIOS_PATH:-/mnt/SDCARD/Bios}/N64"

show_msg() {
	minui-presenter --message "$1" --timeout 0 --confirm-show --confirm-text "OK" >/dev/null 2>&1
}

confirm_msg() {
	minui-presenter --message "$1" --timeout 0 --confirm-show --confirm-text "START" --cancel-show --cancel-text "CANCEL" >/dev/null 2>&1
}

unpack_savestates() {
	unpacked=0
	for gz in "$PAK_DIR/states/"*.st0.gz; do
		[ -f "$gz" ] || continue
		st="${gz%.gz}"
		if [ ! -f "$st" ]; then
			if [ "$unpacked" -eq 0 ]; then
				minui-presenter --message "Unpacking reference savestates..." --timeout 1 >/dev/null 2>&1 || true
			fi
			if gzip -dc "$gz" > "${st}.tmp" 2>/dev/null; then
				mv -f "${st}.tmp" "$st"
				unpacked=$((unpacked + 1))
			else
				rm -f "${st}.tmp"
			fi
		fi
	done
}

read_battery_pct() {
	for p in \
		/sys/class/power_supply/battery/capacity \
		/sys/class/power_supply/BAT0/capacity \
		/sys/class/power_supply/axp2202-battery/capacity \
		/sys/class/power_supply/*/capacity
	do
		[ -r "$p" ] || continue
		val="$(tr -dc '0-9' < "$p" 2>/dev/null)"
		if [ -n "$val" ] && [ "$val" -ge 0 ] && [ "$val" -le 100 ]; then
			printf '%s\n' "$val"
			return 0
		fi
	done
	printf -- '-1\n'
}

preflight_field() {
	printf '%s\n' "$1" | sed -n "s/^${2}=//p" | head -n 1
}

format_battery_line() {
	bat_pct="$1"
	if [ -z "$bat_pct" ] || [ "$bat_pct" -lt 0 ] 2>/dev/null; then
		printf 'Battery: unknown'
	elif [ "$bat_pct" -lt 50 ]; then
		printf 'Battery: %s%% (LOW - plug in charger!)' "$bat_pct"
	else
		printf 'Battery: %s%%' "$bat_pct"
	fi
}

bundle_run_dir() {
	target_dir="$1"
	LAST_BUNDLE_PATH=""
	LAST_MIRROR_PATH=""
	[ -d "$target_dir" ] || return 1

	run_base="$(basename "$target_dir")"
	if [ -n "$LOG_FILE" ] && [ -f "$LOG_FILE" ]; then
		cp -f "$LOG_FILE" "$target_dir/bench.log" 2>/dev/null || true
	fi

	bundle_name="N64Bench_${PLATFORM}_${run_base}.tar.gz"
	bundle_path="$RESULTS_ROOT/$bundle_name"
	if ! (cd "$RESULTS_ROOT" && tar -czf "$bundle_path" "$run_base"); then
		return 1
	fi
	LAST_BUNDLE_PATH="$bundle_path"

	sd_root="${SDCARD_PATH:-/mnt/SDCARD}"
	if [ -d "$sd_root" ] && [ -w "$sd_root" ]; then
		sd_sub="$sd_root/N64Bench-Submissions"
		if mkdir -p "$sd_sub" 2>/dev/null && cp -f "$bundle_path" "$sd_sub/$bundle_name" 2>/dev/null; then
			LAST_MIRROR_PATH="$sd_sub/$bundle_name"
		fi
	fi
	return 0
}

if [ ! -x "$BENCHCTL" ] || [ ! -x "$MINARCH_BENCH" ]; then
	show_msg "Missing binaries for platform '$PLATFORM'.\nExpected bin/$PLATFORM/benchctl and minarch-bench.elf."
	exit 1
fi

unpack_savestates

lookup_id_by_name() {
	tsv_file="$1"
	wanted="$2"
	while IFS="$TAB" read -r item_name item_id; do
		if [ "$item_name" = "$wanted" ]; then
			printf '%s\n' "$item_id"
			return 0
		fi
	done < "$tsv_file"
	return 1
}

run_preflight_check() {
	pf_out="$("$BENCHCTL" preflight "$SCENARIOS_JSON" "$PAK_DIR" 2>/dev/null)"
	r_found="$(preflight_field "$pf_out" "ROMS_FOUND")"
	r_total="$(preflight_field "$pf_out" "ROMS_TOTAL")"
	s_found="$(preflight_field "$pf_out" "STATES_FOUND")"
	s_total="$(preflight_field "$pf_out" "STATES_TOTAL")"
	bat_pct="$(preflight_field "$pf_out" "BATTERY_PCT")"
	soc_mod="$(preflight_field "$pf_out" "SOC_MODEL")"
	next_ver="$(preflight_field "$pf_out" "NEXTUI_VERSION")"
	missing="$(preflight_field "$pf_out" "MISSING")"

	[ -z "$bat_pct" ] && bat_pct="$(read_battery_pct)"
	bat_line="$(format_battery_line "$bat_pct")"

	PF_MSG="Device: $DEV_TAG ($PLATFORM)\nSoC: ${soc_mod:-unknown}\nNextUI: ${next_ver:-unknown} | Pak v${PAK_VERSION}\nROMs: ${r_found:-0}/${r_total:-0} | States: ${s_found:-0}/${s_total:-0}\n$bat_line"
	if [ -n "$missing" ]; then
		PF_MSG="$PF_MSG\nMissing: $missing"
	fi
	show_msg "Preflight Check\n\n$PF_MSG"
}

bundle_last_result() {
	newest=""
	newest_ts=0
	for d in "$RESULTS_ROOT"/*/; do
		[ -d "$d" ] || continue
		[ -f "${d}summary.json" ] || continue
		d_clean="${d%/}"
		d_base="$(basename "$d_clean")"
		d_ts="$(printf '%s' "${d_base##*_}" | tr -cd '0-9')"
		if [ -n "$d_ts" ] && [ "$d_ts" -gt "$newest_ts" ] 2>/dev/null; then
			newest="$d_clean"
			newest_ts="$d_ts"
		elif [ -z "$newest" ]; then
			newest="$d_clean"
		fi
	done
	if [ -z "$newest" ]; then
		show_msg "No completed benchmark results found to bundle."
		return 1
	fi
	if bundle_run_dir "$newest"; then
		msg="Bundled: results/$(basename "$LAST_BUNDLE_PATH")"
		if [ -n "$LAST_MIRROR_PATH" ]; then
			msg="$msg\nSubmission copy: $LAST_MIRROR_PATH"
		fi
		show_msg "Bundle Ready!\n\n$msg"
	else
		show_msg "Failed to create result archive for $(basename "$newest")."
	fi
}

run_genstate_plan_tsv() {
	tsv_path="$1"
	mkdir -p "$PAK_DIR/states"
	GEN_SAVED=0
	GEN_ABORTED=0
	GEN_FAILED=0

	while IFS="$TAB" read -r g_sid g_sname g_core g_rom g_state g_frame g_cfg g_inputs; do
		[ -n "$g_sid" ] || continue
		rm -f "$GEN_META"
		echo "=== Generating savestate: $g_sid (frame=$g_frame) ==="
		BENCH_ENABLE=1 \
		BENCH_TAG="N64" \
		BENCH_MODE="genstate" \
		BENCH_CAPTURE_FRAME="$g_frame" \
		BENCH_CFG_PATH="$g_cfg" \
		BENCH_INPUT_FILE="$g_inputs" \
		BENCH_OUT_STATE="$g_state" \
		BENCH_OUT_META="$GEN_META" \
		BENCH_LABEL="$g_sid" \
		"$MINARCH_BENCH" "$g_core" "$g_rom"
		GRC=$?

		if [ "$GRC" -eq 0 ] && [ -f "$g_state" ]; then
			GEN_SAVED=$((GEN_SAVED + 1))
		elif [ "$GRC" -eq 42 ]; then
			GEN_ABORTED=1
			break
		else
			GEN_FAILED=$((GEN_FAILED + 1))
		fi
	done < "$tsv_path"
}

execute_plan() {
	scope="$1"
	target_id="$2"
	title="$3"

	rm -f "$PLAN_TSV"
	PLAN_INFO="$("$BENCHCTL" plan "$PROFILES_JSON" "$SCENARIOS_JSON" "$PAK_DIR" "$PLATFORM" "$scope" "$target_id" "$MODE" "$WORK_DIR" "$PLAN_TSV")"
	TOTAL_RUNS="$(printf '%s\n' "$PLAN_INFO" | sed -n 's/.*PLANNED=\([0-9]*\).*/\1/p')"
	SKIPPED_SCENS="$(printf '%s\n' "$PLAN_INFO" | sed -n 's/.*SKIPPED_SCENARIOS=\([0-9]*\).*/\1/p')"

	if [ -z "$TOTAL_RUNS" ] || [ "$TOTAL_RUNS" -eq 0 ] || [ "${SKIPPED_SCENS:-0}" -gt 0 ]; then
		rm -f "$GEN_TSV"
		GEN_INFO="$("$BENCHCTL" genstate-plan "$PROFILES_JSON" "$SCENARIOS_JSON" "$PAK_DIR" "$PLATFORM" "missing" "$WORK_DIR" "$GEN_TSV" 2>/dev/null)"
		GEN_PLANNED="$(printf '%s\n' "$GEN_INFO" | sed -n 's/.*PLANNED=\([0-9]*\).*/\1/p')"
		if [ -n "$GEN_PLANNED" ] && [ "$GEN_PLANNED" -gt 0 ]; then
			if confirm_msg "$GEN_PLANNED missing savestate(s) can be auto-generated now.\n\nGenerate missing savestates before benchmarking?"; then
				run_genstate_plan_tsv "$GEN_TSV"
				rm -f "$PLAN_TSV"
				PLAN_INFO="$("$BENCHCTL" plan "$PROFILES_JSON" "$SCENARIOS_JSON" "$PAK_DIR" "$PLATFORM" "$scope" "$target_id" "$MODE" "$WORK_DIR" "$PLAN_TSV")"
				TOTAL_RUNS="$(printf '%s\n' "$PLAN_INFO" | sed -n 's/.*PLANNED=\([0-9]*\).*/\1/p')"
				SKIPPED_SCENS="$(printf '%s\n' "$PLAN_INFO" | sed -n 's/.*SKIPPED_SCENARIOS=\([0-9]*\).*/\1/p')"
			fi
		fi
	fi

	if [ -z "$TOTAL_RUNS" ] || [ "$TOTAL_RUNS" -eq 0 ]; then
		show_msg "No runnable benchmarks found!\n\nPlace ROMs in N64Bench.pak/roms/ (or /mnt/SDCARD/Roms/N64/) and generate or copy savestates into N64Bench.pak/states/.\n\nSkipped missing scenarios: ${SKIPPED_SCENS:-0}"
		return 1
	fi

	PF_OUT="$("$BENCHCTL" preflight "$SCENARIOS_JSON" "$PAK_DIR" 2>/dev/null)"
	PF_RF="$(preflight_field "$PF_OUT" "ROMS_FOUND")"
	PF_RT="$(preflight_field "$PF_OUT" "ROMS_TOTAL")"
	PF_SF="$(preflight_field "$PF_OUT" "STATES_FOUND")"
	PF_ST="$(preflight_field "$PF_OUT" "STATES_TOTAL")"
	PF_BAT="$(preflight_field "$PF_OUT" "BATTERY_PCT")"
	[ -z "$PF_BAT" ] && PF_BAT="$(read_battery_pct)"
	BAT_LINE="$(format_battery_line "$PF_BAT")"

	MSG="Ready: $title\nDevice: $DEV_TAG ($PLATFORM)\nROMs: ${PF_RF:-?}/${PF_RT:-?} | States: ${PF_SF:-?}/${PF_ST:-?}\n$BAT_LINE\nRuns: $TOTAL_RUNS (mode: $MODE, skipped: ${SKIPPED_SCENS:-0})\n\nHold MENU during any run to abort early."
	if ! confirm_msg "$MSG"; then
		return 0
	fi

	TS="$(date +%Y%m%d-%H%M%S)"
	RUN_DIR="$RESULTS_ROOT/${DEV_TAG}_${TS}"
	mkdir -p "$RUN_DIR/runs" "$RUN_DIR/frames"

	BAT_START="$(read_battery_pct)"
	IDX=0
	ABORTED=0
	STATE_ERRORS=0

	while IFS="$TAB" read -r run_id sid sname pid plabel core_file core_path renderer res run_mode rom_path state_path warmup dur target_fps cfg_file input_file; do
		[ -n "$run_id" ] || continue
		IDX=$((IDX + 1))

		echo "=== [$IDX/$TOTAL_RUNS] $run_id ==="
		BENCH_ENABLE=1 \
		BENCH_TAG="N64" \
		BENCH_MODE="$run_mode" \
		BENCH_CFG_PATH="$cfg_file" \
		BENCH_STATE_PATH="$state_path" \
		BENCH_INPUT_FILE="$input_file" \
		BENCH_WARMUP_FRAMES="$warmup" \
		BENCH_DURATION_SEC="$dur" \
		BENCH_LABEL="$IDX/$TOTAL_RUNS: $sid | $plabel" \
		BENCH_OUT_JSON="$RUN_DIR/runs/${run_id}.json" \
		BENCH_OUT_CSV="$RUN_DIR/frames/${run_id}.csv" \
		"$MINARCH_BENCH" "$core_path" "$rom_path"
		RC=$?

		if [ "$RC" -eq 42 ]; then
			ABORTED=1
			echo "Benchmark suite aborted by user on run $IDX/$TOTAL_RUNS"
			break
		elif [ "$RC" -eq 2 ]; then
			STATE_ERRORS=$((STATE_ERRORS + 1))
			echo "Warning: savestate load failed on $run_id"
		elif [ "$RC" -ne 0 ]; then
			echo "Warning: minarch-bench exited with code $RC on $run_id"
		fi

		sleep 2
	done < "$PLAN_TSV"

	BAT_END="$(read_battery_pct)"
	BENCH_PAK_VERSION="$PAK_VERSION" \
	BENCH_SCOPE="$scope" \
	BENCH_TARGET="$target_id" \
	BENCH_MODE_SELECTED="$MODE" \
	BENCH_BAT_START="$BAT_START" \
	BENCH_BAT_END="$BAT_END" \
	"$BENCHCTL" aggregate "$PLAN_TSV" "$RUN_DIR" "$PLATFORM" "$DEV_TAG" \
		"$RUN_DIR/summary.json" "$RUN_DIR/summary.csv" "$RUN_DIR/summary.txt"
	cp "$RUN_DIR/summary.txt" "$LAST_SUMMARY_TXT" 2>/dev/null || true

	BUNDLE_INFO=""
	if bundle_run_dir "$RUN_DIR"; then
		BUNDLE_INFO="Bundle: results/$(basename "$LAST_BUNDLE_PATH")"
		if [ -n "$LAST_MIRROR_PATH" ]; then
			BUNDLE_INFO="$BUNDLE_INFO\nSubmit file: $LAST_MIRROR_PATH"
		fi
	fi

	DONE_NOTE="Benchmark Complete!"
	if [ "$ABORTED" -eq 1 ]; then
		DONE_NOTE="Benchmark Stopped Early ($IDX/$TOTAL_RUNS)"
	fi
	if [ "$STATE_ERRORS" -gt 0 ]; then
		DONE_NOTE="$DONE_NOTE\n($STATE_ERRORS savestate load failure(s))"
	fi

	SUMMARY_PREVIEW="$(head -n 10 "$RUN_DIR/summary.txt" 2>/dev/null)"
	show_msg "$DONE_NOTE\n$BUNDLE_INFO\n\n$SUMMARY_PREVIEW"
}

pick_tier() {
	"$BENCHCTL" list-tiers "$PROFILES_JSON" "$SUB_JSON" > "$SUB_TSV"
	minui-list --disable-auto-sleep --file "$SUB_JSON" --format json --title "Select Benchmark Tier" --confirm-text "RUN" --write-location "$SUB_OUT" >/dev/null
	[ $? -eq 0 ] && [ -f "$SUB_OUT" ] || return
	SEL_NAME="$(cat "$SUB_OUT")"
	SEL_ID="$(lookup_id_by_name "$SUB_TSV" "$SEL_NAME")"
	[ -n "$SEL_ID" ] && execute_plan "tier" "$SEL_ID" "$SEL_NAME"
}

pick_profile() {
	"$BENCHCTL" list-profiles "$PROFILES_JSON" "$SUB_JSON" > "$SUB_TSV"
	minui-list --disable-auto-sleep --file "$SUB_JSON" --format json --title "Select Single Profile" --confirm-text "RUN" --write-location "$SUB_OUT" >/dev/null
	[ $? -eq 0 ] && [ -f "$SUB_OUT" ] || return
	SEL_NAME="$(cat "$SUB_OUT")"
	SEL_ID="$(lookup_id_by_name "$SUB_TSV" "$SEL_NAME")"
	[ -n "$SEL_ID" ] && execute_plan "profile" "$SEL_ID" "$SEL_NAME"
}

pick_scenario() {
	"$BENCHCTL" list-scenarios "$SCENARIOS_JSON" "$PAK_DIR" "$SUB_JSON" > "$SUB_TSV"
	minui-list --disable-auto-sleep --file "$SUB_JSON" --format json --title "Select Single Scenario" --confirm-text "RUN" --write-location "$SUB_OUT" >/dev/null
	[ $? -eq 0 ] && [ -f "$SUB_OUT" ] || return
	SEL_NAME="$(cat "$SUB_OUT")"
	SEL_ID="$(lookup_id_by_name "$SUB_TSV" "$SEL_NAME")"
	[ -n "$SEL_ID" ] && execute_plan "scenario" "$SEL_ID" "$SEL_NAME"
}

generate_missing_states() {
	rm -f "$GEN_TSV"
	GEN_INFO="$("$BENCHCTL" genstate-plan "$PROFILES_JSON" "$SCENARIOS_JSON" "$PAK_DIR" "$PLATFORM" "missing" "$WORK_DIR" "$GEN_TSV" 2>"$WORK_DIR/genstate.err")"
	if [ $? -ne 0 ]; then
		ERR_MSG="$(cat "$WORK_DIR/genstate.err" 2>/dev/null)"
		show_msg "Cannot plan savestate generation:\n\n${ERR_MSG:-Check configuration and bundled ReARMed core.}"
		return 1
	fi

	GEN_PLANNED="$(printf '%s\n' "$GEN_INFO" | sed -n 's/.*PLANNED=\([0-9]*\).*/\1/p')"
	GEN_NO_ROM="$(printf '%s\n' "$GEN_INFO" | sed -n 's/.*SKIPPED_NO_ROM=\([0-9]*\).*/\1/p')"
	GEN_NO_FRAME="$(printf '%s\n' "$GEN_INFO" | sed -n 's/.*SKIPPED_NO_FRAME=\([0-9]*\).*/\1/p')"

	if [ -z "$GEN_PLANNED" ] || [ "$GEN_PLANNED" -eq 0 ]; then
		if [ "${GEN_NO_FRAME:-0}" -gt 0 ]; then
			show_msg "No auto-generatable missing savestates.\n\n$GEN_NO_FRAME missing scenario(s) have capture_frame=0 (not configured yet).\n\nUse 'Capture State / Find Frame' to capture them interactively and log exact frame numbers."
		elif [ "${GEN_NO_ROM:-0}" -gt 0 ]; then
			show_msg "No auto-generatable missing savestates ($GEN_NO_ROM missing ROM(s))."
		else
			show_msg "All savestates for available ROMs already exist."
		fi
		return 0
	fi

	if ! confirm_msg "Generate $GEN_PLANNED missing savestate(s) automatically?\n\nDeterministic cold boot with bundled ReARMed.\nHold MENU anytime to abort."; then
		return 0
	fi

	run_genstate_plan_tsv "$GEN_TSV"
	if [ "$GEN_ABORTED" -eq 1 ]; then
		show_msg "Savestate Generation Aborted\n\nSaved: $GEN_SAVED / $GEN_PLANNED"
	elif [ "$GEN_FAILED" -gt 0 ]; then
		show_msg "Savestate Generation Finished\n\nSaved: $GEN_SAVED | Failed: $GEN_FAILED"
	else
		show_msg "Savestates Generated!\n\nSaved: $GEN_SAVED savestate(s) into states/."
	fi
}

capture_state_interactive() {
	"$BENCHCTL" list-scenarios "$SCENARIOS_JSON" "$PAK_DIR" "$SUB_JSON" > "$SUB_TSV"
	minui-list --disable-auto-sleep --file "$SUB_JSON" --format json --title "Capture State / Find Frame" --confirm-text "CAPTURE" --write-location "$SUB_OUT" >/dev/null
	[ $? -eq 0 ] && [ -f "$SUB_OUT" ] || return
	SEL_NAME="$(cat "$SUB_OUT")"
	SEL_ID="$(lookup_id_by_name "$SUB_TSV" "$SEL_NAME")"
	[ -n "$SEL_ID" ] || return

	rm -f "$GEN_TSV" "$GEN_META"
	"$BENCHCTL" genstate-plan "$PROFILES_JSON" "$SCENARIOS_JSON" "$PAK_DIR" "$PLATFORM" "$SEL_ID" "$WORK_DIR" "$GEN_TSV" >/dev/null 2>"$WORK_DIR/genstate.err"
	if [ $? -ne 0 ] || [ ! -s "$GEN_TSV" ]; then
		ERR_MSG="$(cat "$WORK_DIR/genstate.err" 2>/dev/null)"
		show_msg "Cannot capture '$SEL_ID':\n\n${ERR_MSG:-Missing ROM or bundled ReARMed core.}"
		return 1
	fi

	IFS="$TAB" read -r c_sid c_sname c_core c_rom c_state c_frame c_cfg c_inputs < "$GEN_TSV"
	if [ -z "$c_sid" ]; then
		show_msg "Cannot capture '$SEL_ID': missing ROM."
		return 1
	fi

	CAP_PROMPT="Capture savestate for ${c_sname:-$c_sid}\n\n- Hold R1: Fast-Forward past intros\n- Tap A: Capture & Save State\n- Hold MENU: Cancel\n\nSaves to: states/${c_sid}.st0"
	if ! confirm_msg "$CAP_PROMPT"; then
		return 0
	fi

	mkdir -p "$PAK_DIR/states"
	BENCH_ENABLE=1 \
	BENCH_TAG="N64" \
	BENCH_MODE="genstate" \
	BENCH_CAPTURE_FRAME="0" \
	BENCH_CFG_PATH="$c_cfg" \
	BENCH_INPUT_FILE="$c_inputs" \
	BENCH_OUT_STATE="$c_state" \
	BENCH_OUT_META="$GEN_META" \
	BENCH_LABEL="$c_sid" \
	"$MINARCH_BENCH" "$c_core" "$c_rom"
	RC=$?

	if [ "$RC" -eq 0 ] && [ -f "$c_state" ]; then
		CAP_FRAME="$(sed -n 's/^CAPTURE_FRAME=//p' "$GEN_META" 2>/dev/null | head -n 1)"
		[ -n "$CAP_FRAME" ] && printf '%s %s\n' "$c_sid" "$CAP_FRAME" >> "$PAK_DIR/states/capture_frames.txt"
		show_msg "Saved states/${c_sid}.st0 at frame ${CAP_FRAME:-?}!\n\nLogged frame to states/capture_frames.txt."
	elif [ "$RC" -eq 42 ]; then
		show_msg "Savestate capture canceled; existing state unchanged."
	else
		show_msg "Savestate capture failed (exit code $RC)."
	fi
}

cycle_mode() {
	case "$MODE" in
		both)     MODE="paced" ;;
		paced)    MODE="uncapped" ;;
		uncapped) MODE="both" ;;
		*)        MODE="both" ;;
	esac
}

while true; do
	cat > "$MENU_JSON" <<EOF
["Run Benchmark Tier (Recommended)","Run Full Suite (All Profiles)","Run Single Profile","Run Single Scenario","Generate Missing Savestates (Auto)","Capture State / Find Frame","Mode: $MODE","Check Setup / Preflight","Bundle Last Result","View Last Summary","Exit"]
EOF
	rm -f "$CHOICE_OUT"
	minui-list --disable-auto-sleep --file "$MENU_JSON" --format json --title "N64 Benchmark ($PLATFORM)" --confirm-text "SELECT" --write-location "$CHOICE_OUT" >/dev/null
	RC=$?
	if [ "$RC" -ne 0 ] || [ ! -f "$CHOICE_OUT" ]; then
		break
	fi

	CHOICE="$(cat "$CHOICE_OUT")"
	case "$CHOICE" in
		"Run Benchmark Tier (Recommended)")
			pick_tier
			;;
		"Run Full Suite (All Profiles)")
			execute_plan "all" "all" "Full Suite (All Profiles)"
			;;
		"Run Single Profile")
			pick_profile
			;;
		"Run Single Scenario")
			pick_scenario
			;;
		"Generate Missing Savestates (Auto)")
			generate_missing_states
			;;
		"Capture State / Find Frame")
			capture_state_interactive
			;;
		"Mode: "*)
			cycle_mode
			;;
		"Check Setup / Preflight")
			run_preflight_check
			;;
		"Bundle Last Result")
			bundle_last_result
			;;
		"View Last Summary")
			if [ -f "$LAST_SUMMARY_TXT" ]; then
				show_msg "$(head -n 16 "$LAST_SUMMARY_TXT")"
			else
				show_msg "No benchmark results yet."
			fi
			;;
		"Exit"|"")
			break
			;;
	esac
done

rm -rf "$WORK_DIR"
exit 0

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
RESULTS_ROOT="$PAK_DIR/results"
LAST_SUMMARY_TXT="$RESULTS_ROOT/last_summary.txt"

WORK_DIR="/tmp/${PAK_NAME}-work"
MENU_JSON="$WORK_DIR/menu.json"
CHOICE_OUT="$WORK_DIR/choice.out"
SUB_JSON="$WORK_DIR/sub.json"
SUB_TSV="$WORK_DIR/sub.tsv"
SUB_OUT="$WORK_DIR/sub.out"
PLAN_TSV="$WORK_DIR/plan.tsv"

TAB="$(printf '\t')"
MODE="both"

mkdir -p "$WORK_DIR" "$RESULTS_ROOT"

show_msg() {
	minui-presenter --message "$1" --timeout 0 --confirm-show --confirm-text "OK" >/dev/null 2>&1
}

confirm_msg() {
	minui-presenter --message "$1" --timeout 0 --confirm-show --confirm-text "START" --cancel-show --cancel-text "CANCEL" >/dev/null 2>&1
}

if [ ! -x "$BENCHCTL" ] || [ ! -x "$MINARCH_BENCH" ]; then
	show_msg "Missing binaries for platform '$PLATFORM'.\nExpected bin/$PLATFORM/benchctl and minarch-bench.elf."
	exit 1
fi

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

execute_plan() {
	scope="$1"
	target_id="$2"
	title="$3"

	rm -f "$PLAN_TSV"
	PLAN_INFO="$("$BENCHCTL" plan "$PROFILES_JSON" "$SCENARIOS_JSON" "$PAK_DIR" "$PLATFORM" "$scope" "$target_id" "$MODE" "$WORK_DIR" "$PLAN_TSV")"
	TOTAL_RUNS="$(printf '%s\n' "$PLAN_INFO" | sed -n 's/.*PLANNED=\([0-9]*\).*/\1/p')"
	SKIPPED_SCENS="$(printf '%s\n' "$PLAN_INFO" | sed -n 's/.*SKIPPED_SCENARIOS=\([0-9]*\).*/\1/p')"

	if [ -z "$TOTAL_RUNS" ] || [ "$TOTAL_RUNS" -eq 0 ]; then
		show_msg "No runnable benchmarks found!\n\nPlace ROMs in N64Bench.pak/roms/ and matching ReARMed savestates in N64Bench.pak/states/ (or edit config/scenarios.json).\n\nSkipped missing scenarios: ${SKIPPED_SCENS:-0}"
		return 1
	fi

	DEV_TAG="${DEVICE:-$PLATFORM}"
	TS="$(date +%Y%m%d-%H%M%S)"
	RUN_DIR="$RESULTS_ROOT/${DEV_TAG}_${TS}"
	mkdir -p "$RUN_DIR/runs" "$RUN_DIR/frames"

	MSG="Ready to run: $title\n\nRuns: $TOTAL_RUNS (mode: $MODE)\nSkipped missing scenarios: ${SKIPPED_SCENS:-0}\n\nHold MENU during any run to abort early."
	if ! confirm_msg "$MSG"; then
		return 0
	fi

	IDX=0
	ABORTED=0
	STATE_ERRORS=0

	while IFS="$TAB" read -r run_id sid sname pid plabel core_file core_path renderer res run_mode rom_path state_path warmup dur target_fps cfg_file input_file; do
		[ -n "$run_id" ] || continue
		IDX=$((IDX + 1))

		echo "=== [$IDX/$TOTAL_RUNS] $run_id ==="
		BENCH_ENABLE=1 \
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

	"$BENCHCTL" aggregate "$PLAN_TSV" "$RUN_DIR" "$PLATFORM" "$DEV_TAG" \
		"$RUN_DIR/summary.json" "$RUN_DIR/summary.csv" "$RUN_DIR/summary.txt"
	cp "$RUN_DIR/summary.txt" "$LAST_SUMMARY_TXT" 2>/dev/null || true

	DONE_NOTE="Benchmark Complete!"
	if [ "$ABORTED" -eq 1 ]; then
		DONE_NOTE="Benchmark Stopped Early ($IDX/$TOTAL_RUNS)"
	fi
	if [ "$STATE_ERRORS" -gt 0 ]; then
		DONE_NOTE="$DONE_NOTE\n($STATE_ERRORS savestate load failure(s))"
	fi

	SUMMARY_PREVIEW="$(head -n 12 "$RUN_DIR/summary.txt" 2>/dev/null)"
	show_msg "$DONE_NOTE\nSaved to: results/$(basename "$RUN_DIR")\n\n$SUMMARY_PREVIEW"
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
{"items":[
  {"name":"Run Benchmark Tier (Recommended)"},
  {"name":"Run Full Suite (All Profiles)"},
  {"name":"Run Single Profile"},
  {"name":"Run Single Scenario"},
  {"name":"Mode: $MODE"},
  {"name":"View Last Summary"},
  {"name":"Exit"}
]}
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
		"Mode: "*)
			cycle_mode
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

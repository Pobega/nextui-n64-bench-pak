/*
 * benchctl - Configuration planner, menu generator, and telemetry aggregator
 * for NextUI N64Bench.pak. Zero external runtime dependencies (pure C99).
 */

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#define MAX_PROFILES       64
#define MAX_TIERS          16
#define MAX_TIER_PROFILES  32
#define MAX_OPTIONS        64
#define MAX_SCENARIOS      64
#define MAX_INPUT_STEPS    128
#define MAX_PATH_LEN       1024
#define MAX_STR_LEN        256
#define MAX_RUNS           1024

/* Libretro joypad button IDs matching libretro.h */
enum {
	JOY_B      = 0,
	JOY_Y      = 1,
	JOY_SELECT = 2,
	JOY_START  = 3,
	JOY_UP     = 4,
	JOY_DOWN   = 5,
	JOY_LEFT   = 6,
	JOY_RIGHT  = 7,
	JOY_A      = 8,
	JOY_X      = 9,
	JOY_L      = 10,
	JOY_R      = 11,
	JOY_L2     = 12,
	JOY_R2     = 13
};

/* Minimal DOM JSON parser */
typedef enum {
	JSON_NULL,
	JSON_BOOL,
	JSON_NUM,
	JSON_STR,
	JSON_ARR,
	JSON_OBJ
} JsonType;

typedef struct JsonVal JsonVal;
typedef struct {
	char    *key;
	JsonVal *val;
} JsonPair;

struct JsonVal {
	JsonType type;
	double   num;
	int      boolean;
	char    *str;
	JsonVal **items;
	size_t   count;
	JsonPair *pairs;
};

typedef struct {
	const char *s;
	size_t      pos;
} JsonParser;

static void json_skip_ws(JsonParser *p) {
	while (p->s[p->pos] && isspace((unsigned char)p->s[p->pos])) p->pos++;
}

static JsonVal *json_alloc(JsonType t) {
	JsonVal *v = calloc(1, sizeof(JsonVal));
	if (v) v->type = t;
	return v;
}

static void json_free(JsonVal *v) {
	if (!v) return;
	if (v->type == JSON_STR) free(v->str);
	else if (v->type == JSON_ARR) {
		for (size_t i = 0; i < v->count; i++) json_free(v->items[i]);
		free(v->items);
	}
	else if (v->type == JSON_OBJ) {
		for (size_t i = 0; i < v->count; i++) {
			free(v->pairs[i].key);
			json_free(v->pairs[i].val);
		}
		free(v->pairs);
	}
	free(v);
}

static char *json_parse_string_raw(JsonParser *p) {
	if (p->s[p->pos] != '"') return NULL;
	p->pos++;
	size_t cap = 64, len = 0;
	char *out = malloc(cap);
	if (!out) return NULL;
	while (p->s[p->pos] && p->s[p->pos] != '"') {
		char c = p->s[p->pos++];
		if (c == '\\' && p->s[p->pos]) {
			char esc = p->s[p->pos++];
			switch (esc) {
				case '"':  c = '"'; break;
				case '\\': c = '\\'; break;
				case '/':  c = '/'; break;
				case 'n':  c = '\n'; break;
				case 'r':  c = '\r'; break;
				case 't':  c = '\t'; break;
				default:   c = esc; break;
			}
		}
		if (len + 2 >= cap) {
			cap *= 2;
			char *grown = realloc(out, cap);
			if (!grown) { free(out); return NULL; }
			out = grown;
		}
		out[len++] = c;
	}
	if (p->s[p->pos] == '"') p->pos++;
	out[len] = '\0';
	return out;
}

static JsonVal *json_parse_val(JsonParser *p);

static JsonVal *json_parse_array(JsonParser *p) {
	p->pos++; /* '[' */
	JsonVal *arr = json_alloc(JSON_ARR);
	size_t cap = 0;
	json_skip_ws(p);
	if (p->s[p->pos] == ']') { p->pos++; return arr; }
	while (p->s[p->pos]) {
		json_skip_ws(p);
		JsonVal *item = json_parse_val(p);
		if (!item) break;
		if (arr->count >= cap) {
			cap = cap ? cap * 2 : 8;
			arr->items = realloc(arr->items, cap * sizeof(JsonVal *));
		}
		arr->items[arr->count++] = item;
		json_skip_ws(p);
		if (p->s[p->pos] == ',') { p->pos++; continue; }
		if (p->s[p->pos] == ']') { p->pos++; break; }
		break;
	}
	return arr;
}

static JsonVal *json_parse_object(JsonParser *p) {
	p->pos++; /* '{' */
	JsonVal *obj = json_alloc(JSON_OBJ);
	size_t cap = 0;
	json_skip_ws(p);
	if (p->s[p->pos] == '}') { p->pos++; return obj; }
	while (p->s[p->pos]) {
		json_skip_ws(p);
		char *key = json_parse_string_raw(p);
		if (!key) break;
		json_skip_ws(p);
		if (p->s[p->pos] == ':') p->pos++;
		json_skip_ws(p);
		JsonVal *val = json_parse_val(p);
		if (!val) { free(key); break; }
		if (obj->count >= cap) {
			cap = cap ? cap * 2 : 8;
			obj->pairs = realloc(obj->pairs, cap * sizeof(JsonPair));
		}
		obj->pairs[obj->count].key = key;
		obj->pairs[obj->count].val = val;
		obj->count++;
		json_skip_ws(p);
		if (p->s[p->pos] == ',') { p->pos++; continue; }
		if (p->s[p->pos] == '}') { p->pos++; break; }
		break;
	}
	return obj;
}

static JsonVal *json_parse_val(JsonParser *p) {
	json_skip_ws(p);
	char c = p->s[p->pos];
	if (c == '"') {
		JsonVal *v = json_alloc(JSON_STR);
		v->str = json_parse_string_raw(p);
		return v;
	}
	if (c == '[') return json_parse_array(p);
	if (c == '{') return json_parse_object(p);
	if (strncmp(p->s + p->pos, "true", 4) == 0) {
		p->pos += 4;
		JsonVal *v = json_alloc(JSON_BOOL);
		v->boolean = 1;
		return v;
	}
	if (strncmp(p->s + p->pos, "false", 5) == 0) {
		p->pos += 5;
		return json_alloc(JSON_BOOL);
	}
	if (strncmp(p->s + p->pos, "null", 4) == 0) {
		p->pos += 4;
		return json_alloc(JSON_NULL);
	}
	if (c == '-' || isdigit((unsigned char)c)) {
		char *end = NULL;
		double num = strtod(p->s + p->pos, &end);
		if (end && end != p->s + p->pos) {
			p->pos = (size_t)(end - p->s);
			JsonVal *v = json_alloc(JSON_NUM);
			v->num = num;
			return v;
		}
	}
	return NULL;
}

static char *read_file_all(const char *path) {
	FILE *fp = fopen(path, "rb");
	if (!fp) return NULL;
	fseek(fp, 0, SEEK_END);
	long sz = ftell(fp);
	fseek(fp, 0, SEEK_SET);
	if (sz < 0) { fclose(fp); return NULL; }
	char *buf = malloc((size_t)sz + 1);
	if (!buf) { fclose(fp); return NULL; }
	size_t n = fread(buf, 1, (size_t)sz, fp);
	buf[n] = '\0';
	fclose(fp);
	return buf;
}

static JsonVal *json_load_file(const char *path) {
	char *text = read_file_all(path);
	if (!text) return NULL;
	JsonParser p = { text, 0 };
	JsonVal *root = json_parse_val(&p);
	free(text);
	return root;
}

static JsonVal *json_get(const JsonVal *obj, const char *key) {
	if (!obj || obj->type != JSON_OBJ) return NULL;
	for (size_t i = 0; i < obj->count; i++) {
		if (strcmp(obj->pairs[i].key, key) == 0) return obj->pairs[i].val;
	}
	return NULL;
}

static const char *json_str(const JsonVal *obj, const char *key, const char *fallback) {
	JsonVal *v = json_get(obj, key);
	return (v && v->type == JSON_STR && v->str) ? v->str : fallback;
}

static double json_num(const JsonVal *obj, const char *key, double fallback) {
	JsonVal *v = json_get(obj, key);
	return (v && v->type == JSON_NUM) ? v->num : fallback;
}

static void json_write_escaped(FILE *fp, const char *s) {
	fputc('"', fp);
	if (s) {
		for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
			if (*p == '"') fputs("\\\"", fp);
			else if (*p == '\\') fputs("\\\\", fp);
			else if (*p == '\n') fputs("\\n", fp);
			else if (*p == '\r') fputs("\\r", fp);
			else if (*p == '\t') fputs("\\t", fp);
			else fputc(*p, fp);
		}
	}
	fputc('"', fp);
}

/* Compact SHA-256 (FIPS 180-4) for core binary fingerprinting */
typedef struct {
	uint32_t state[8];
	uint64_t bitlen;
	uint8_t  data[64];
	size_t   datalen;
} Sha256Ctx;

static const uint32_t SHA256_K[64] = {
	0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
	0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
	0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
	0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
	0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
	0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
	0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
	0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

static inline uint32_t rotr32(uint32_t x, uint32_t n) { return (x >> n) | (x << (32 - n)); }

static void sha256_transform(Sha256Ctx *ctx, const uint8_t block[64]) {
	uint32_t m[64];
	for (int i = 0; i < 16; i++) {
		m[i] = ((uint32_t)block[i*4] << 24) | ((uint32_t)block[i*4+1] << 16) |
		       ((uint32_t)block[i*4+2] << 8) | ((uint32_t)block[i*4+3]);
	}
	for (int i = 16; i < 64; i++) {
		uint32_t s0 = rotr32(m[i-15], 7) ^ rotr32(m[i-15], 18) ^ (m[i-15] >> 3);
		uint32_t s1 = rotr32(m[i-2], 17) ^ rotr32(m[i-2], 19) ^ (m[i-2] >> 10);
		m[i] = m[i-16] + s0 + m[i-7] + s1;
	}
	uint32_t a=ctx->state[0], b=ctx->state[1], c=ctx->state[2], d=ctx->state[3];
	uint32_t e=ctx->state[4], f=ctx->state[5], g=ctx->state[6], h=ctx->state[7];
	for (int i = 0; i < 64; i++) {
		uint32_t S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
		uint32_t ch = (e & f) ^ ((~e) & g);
		uint32_t t1 = h + S1 + ch + SHA256_K[i] + m[i];
		uint32_t S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
		uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
		uint32_t t2 = S0 + maj;
		h = g; g = f; f = e; e = d + t1;
		d = c; c = b; b = a; a = t1 + t2;
	}
	ctx->state[0]+=a; ctx->state[1]+=b; ctx->state[2]+=c; ctx->state[3]+=d;
	ctx->state[4]+=e; ctx->state[5]+=f; ctx->state[6]+=g; ctx->state[7]+=h;
}

static void sha256_file_hex(const char *path, char out_hex[65]) {
	strcpy(out_hex, "unknown");
	FILE *fp = fopen(path, "rb");
	if (!fp) return;
	Sha256Ctx ctx;
	ctx.datalen = 0;
	ctx.bitlen = 0;
	ctx.state[0]=0x6a09e667; ctx.state[1]=0xbb67ae85; ctx.state[2]=0x3c6ef372; ctx.state[3]=0xa54ff53a;
	ctx.state[4]=0x510e527f; ctx.state[5]=0x9b05688c; ctx.state[6]=0x1f83d9ab; ctx.state[7]=0x5be0cd19;

	uint8_t buf[4096];
	size_t n;
	while ((n = fread(buf, 1, sizeof(buf), fp)) > 0) {
		for (size_t i = 0; i < n; i++) {
			ctx.data[ctx.datalen++] = buf[i];
			if (ctx.datalen == 64) {
				sha256_transform(&ctx, ctx.data);
				ctx.bitlen += 512;
				ctx.datalen = 0;
			}
		}
	}
	fclose(fp);

	size_t i = ctx.datalen;
	ctx.data[i++] = 0x80;
	if (i > 56) {
		while (i < 64) ctx.data[i++] = 0;
		sha256_transform(&ctx, ctx.data);
		i = 0;
	}
	while (i < 56) ctx.data[i++] = 0;
	ctx.bitlen += ctx.datalen * 8;
	for (int j = 7; j >= 0; j--) ctx.data[56 + (7 - j)] = (uint8_t)(ctx.bitlen >> (j * 8));
	sha256_transform(&ctx, ctx.data);

	for (int j = 0; j < 8; j++) sprintf(out_hex + j * 8, "%08x", ctx.state[j]);
	out_hex[64] = '\0';
}

static int file_exists(const char *path) {
	struct stat st;
	return path && path[0] && stat(path, &st) == 0 && S_ISREG(st.st_mode);
}

static void resolve_pak_path(const char *pak_dir, const char *rel_or_abs, char *out, size_t out_sz) {
	if (!rel_or_abs || !rel_or_abs[0]) {
		out[0] = '\0';
		return;
	}
	if (rel_or_abs[0] == '/') {
		snprintf(out, out_sz, "%s", rel_or_abs);
	}
	else {
		snprintf(out, out_sz, "%s/%s", pak_dir, rel_or_abs);
	}
}

static uint32_t parse_button_name(const char *name) {
	if (!name) return 0;
	if (strcmp(name, "B") == 0)      return 1u << JOY_B;
	if (strcmp(name, "Y") == 0)      return 1u << JOY_Y;
	if (strcmp(name, "SELECT") == 0) return 1u << JOY_SELECT;
	if (strcmp(name, "START") == 0)  return 1u << JOY_START;
	if (strcmp(name, "UP") == 0)     return 1u << JOY_UP;
	if (strcmp(name, "DOWN") == 0)   return 1u << JOY_DOWN;
	if (strcmp(name, "LEFT") == 0)   return 1u << JOY_LEFT;
	if (strcmp(name, "RIGHT") == 0)  return 1u << JOY_RIGHT;
	if (strcmp(name, "A") == 0)      return 1u << JOY_A;
	if (strcmp(name, "X") == 0)      return 1u << JOY_X;
	if (strcmp(name, "L") == 0 || strcmp(name, "L1") == 0)  return 1u << JOY_L;
	if (strcmp(name, "R") == 0 || strcmp(name, "R1") == 0)  return 1u << JOY_R;
	if (strcmp(name, "L2") == 0 || strcmp(name, "Z") == 0)  return 1u << JOY_L2;
	if (strcmp(name, "R2") == 0)     return 1u << JOY_R2;
	return 0;
}

static void read_sysfs_line(const char *path, char *out, size_t out_sz, const char *fallback) {
	snprintf(out, out_sz, "%s", fallback);
	FILE *fp = fopen(path, "r");
	if (!fp) return;
	if (fgets(out, (int)out_sz, fp)) {
		size_t n = strlen(out);
		while (n > 0 && (out[n-1] == '\n' || out[n-1] == '\r' || out[n-1] == ' ')) out[--n] = '\0';
	}
	fclose(fp);
}

static int cmd_list_tiers(const char *profiles_path, const char *out_path) {
	JsonVal *root = json_load_file(profiles_path);
	if (!root) { fprintf(stderr, "Failed to load %s\n", profiles_path); return 1; }
	JsonVal *tiers = json_get(root, "tiers");
	FILE *fp = fopen(out_path, "w");
	if (!fp) { json_free(root); return 1; }

	fprintf(fp, "{\"items\":[");
	int first = 1;
	if (tiers && tiers->type == JSON_ARR) {
		for (size_t i = 0; i < tiers->count; i++) {
			JsonVal *t = tiers->items[i];
			const char *id = json_str(t, "id", "");
			const char *name = json_str(t, "name", id);
			if (!first) fputc(',', fp);
			first = 0;
			fprintf(fp, "{\"name\":"); json_write_escaped(fp, name);
			fprintf(fp, ",\"value\":"); json_write_escaped(fp, id);
			fprintf(fp, "}");
			printf("%s\t%s\n", name, id);
		}
	}
	fprintf(fp, "]}\n");
	fclose(fp);
	json_free(root);
	return 0;
}

static int cmd_list_profiles(const char *profiles_path, const char *out_path) {
	JsonVal *root = json_load_file(profiles_path);
	if (!root) return 1;
	JsonVal *profiles = json_get(root, "profiles");
	FILE *fp = fopen(out_path, "w");
	if (!fp) { json_free(root); return 1; }

	fprintf(fp, "{\"items\":[");
	int first = 1;
	if (profiles && profiles->type == JSON_ARR) {
		for (size_t i = 0; i < profiles->count; i++) {
			JsonVal *pr = profiles->items[i];
			const char *id = json_str(pr, "id", "");
			const char *label = json_str(pr, "label", id);
			if (!first) fputc(',', fp);
			first = 0;
			fprintf(fp, "{\"name\":"); json_write_escaped(fp, label);
			fprintf(fp, ",\"value\":"); json_write_escaped(fp, id);
			fprintf(fp, "}");
			printf("%s\t%s\n", label, id);
		}
	}
	fprintf(fp, "]}\n");
	fclose(fp);
	json_free(root);
	return 0;
}

static int cmd_list_scenarios(const char *scenarios_path, const char *pak_dir, const char *out_path) {
	JsonVal *root = json_load_file(scenarios_path);
	if (!root) return 1;
	JsonVal *scens = json_get(root, "scenarios");
	FILE *fp = fopen(out_path, "w");
	if (!fp) { json_free(root); return 1; }

	fprintf(fp, "{\"items\":[");
	int first = 1;
	if (scens && scens->type == JSON_ARR) {
		for (size_t i = 0; i < scens->count; i++) {
			JsonVal *sc = scens->items[i];
			const char *id = json_str(sc, "id", "");
			const char *name = json_str(sc, "name", id);
			char rom_path[MAX_PATH_LEN], state_path[MAX_PATH_LEN];
			resolve_pak_path(pak_dir, json_str(sc, "rom", ""), rom_path, sizeof(rom_path));
			resolve_pak_path(pak_dir, json_str(sc, "state", ""), state_path, sizeof(state_path));

			int rom_ok = file_exists(rom_path);
			int state_ok = !state_path[0] || file_exists(state_path);
			char display[MAX_STR_LEN + 32];
			snprintf(display, sizeof(display), "%s %s", (rom_ok && state_ok) ? "[OK]" : "[MISSING]", name);

			if (!first) fputc(',', fp);
			first = 0;
			fprintf(fp, "{\"name\":"); json_write_escaped(fp, display);
			fprintf(fp, ",\"value\":"); json_write_escaped(fp, id);
			fprintf(fp, "}");
			printf("%s\t%s\n", display, id);
		}
	}
	fprintf(fp, "]}\n");
	fclose(fp);
	json_free(root);
	return 0;
}

static JsonVal *find_profile_by_id(const JsonVal *profiles_arr, const char *id) {
	if (!profiles_arr || profiles_arr->type != JSON_ARR) return NULL;
	for (size_t i = 0; i < profiles_arr->count; i++) {
		if (strcmp(json_str(profiles_arr->items[i], "id", ""), id) == 0)
			return profiles_arr->items[i];
	}
	return NULL;
}

static void write_profile_cfg(const JsonVal *profile, const char *out_cfg_path) {
	FILE *fp = fopen(out_cfg_path, "w");
	if (!fp) return;
	JsonVal *opts = json_get(profile, "options");
	if (opts && opts->type == JSON_OBJ) {
		for (size_t i = 0; i < opts->count; i++) {
			JsonVal *v = opts->pairs[i].val;
			if (v && v->type == JSON_STR && v->str) {
				fprintf(fp, "%s = %s\n", opts->pairs[i].key, v->str);
			}
			else if (v && v->type == JSON_NUM) {
				fprintf(fp, "%s = %.0f\n", opts->pairs[i].key, v->num);
			}
		}
	}
	fclose(fp);
}

static void write_scenario_inputs(const JsonVal *scen, const char *out_input_path) {
	FILE *fp = fopen(out_input_path, "w");
	if (!fp) return;
	JsonVal *inputs = json_get(scen, "inputs");
	if (inputs && inputs->type == JSON_ARR) {
		for (size_t i = 0; i < inputs->count; i++) {
			JsonVal *step = inputs->items[i];
			unsigned start_f = (unsigned)json_num(step, "start", 0);
			unsigned end_f = (unsigned)json_num(step, "end", 0);
			int lx = (int)json_num(step, "lx", 0);
			int ly = (int)json_num(step, "ly", 0);
			uint32_t mask = 0;
			JsonVal *btns = json_get(step, "buttons");
			if (btns && btns->type == JSON_ARR) {
				for (size_t b = 0; b < btns->count; b++) {
					if (btns->items[b] && btns->items[b]->type == JSON_STR) {
						mask |= parse_button_name(btns->items[b]->str);
					}
				}
			}
			fprintf(fp, "%u %u %d %d %u\n", start_f, end_f, lx, ly, mask);
		}
	}
	fclose(fp);
}

/*
 * plan <profiles.json> <scenarios.json> <pak_dir> <platform> <scope> <target_id> <mode> <work_dir> <out_plan.tsv>
 * scope: tier | profile | scenario | all
 * mode:  both | paced | uncapped
 */
static int cmd_plan(int argc, char **argv) {
	if (argc < 11) {
		fprintf(stderr, "Usage: benchctl plan <profiles.json> <scenarios.json> <pak_dir> <platform> <scope> <target_id> <mode> <work_dir> <out_plan.tsv>\n");
		return 1;
	}
	const char *profiles_path = argv[2];
	const char *scenarios_path = argv[3];
	const char *pak_dir = argv[4];
	const char *platform = argv[5];
	const char *scope = argv[6];
	const char *target_id = argv[7];
	const char *mode = argv[8];
	const char *work_dir = argv[9];
	const char *out_plan = argv[10];

	JsonVal *proot = json_load_file(profiles_path);
	JsonVal *sroot = json_load_file(scenarios_path);
	if (!proot || !sroot) {
		fprintf(stderr, "Failed to parse profiles or scenarios JSON\n");
		json_free(proot); json_free(sroot);
		return 1;
	}

	JsonVal *defaults = json_get(proot, "defaults");
	int def_warmup = (int)json_num(defaults, "warmup_frames", 120);
	int def_paced = (int)json_num(defaults, "paced_seconds", 15);
	int def_uncapped = (int)json_num(defaults, "uncapped_seconds", 8);

	JsonVal *profiles_arr = json_get(proot, "profiles");
	JsonVal *tiers_arr = json_get(proot, "tiers");
	JsonVal *scens_arr = json_get(sroot, "scenarios");

	JsonVal *sel_profiles[MAX_PROFILES];
	int sel_profile_count = 0;

	if (strcmp(scope, "tier") == 0 && tiers_arr && tiers_arr->type == JSON_ARR) {
		for (size_t i = 0; i < tiers_arr->count; i++) {
			if (strcmp(json_str(tiers_arr->items[i], "id", ""), target_id) == 0) {
				JsonVal *pids = json_get(tiers_arr->items[i], "profiles");
				if (pids && pids->type == JSON_ARR) {
					for (size_t j = 0; j < pids->count && sel_profile_count < MAX_PROFILES; j++) {
						if (pids->items[j]->type == JSON_STR) {
							JsonVal *p = find_profile_by_id(profiles_arr, pids->items[j]->str);
							if (p) sel_profiles[sel_profile_count++] = p;
						}
					}
				}
				break;
			}
		}
	}
	else if (strcmp(scope, "profile") == 0) {
		JsonVal *p = find_profile_by_id(profiles_arr, target_id);
		if (p) sel_profiles[sel_profile_count++] = p;
	}
	else {
		/* scenario or all: default to quick-240p tier for single scenario, or all profiles for 'all' */
		if (strcmp(scope, "scenario") == 0 && tiers_arr && tiers_arr->type == JSON_ARR && tiers_arr->count > 0) {
			JsonVal *pids = json_get(tiers_arr->items[0], "profiles");
			if (pids && pids->type == JSON_ARR) {
				for (size_t j = 0; j < pids->count && sel_profile_count < MAX_PROFILES; j++) {
					if (pids->items[j]->type == JSON_STR) {
						JsonVal *p = find_profile_by_id(profiles_arr, pids->items[j]->str);
						if (p) sel_profiles[sel_profile_count++] = p;
					}
				}
			}
		}
		else if (profiles_arr && profiles_arr->type == JSON_ARR) {
			for (size_t i = 0; i < profiles_arr->count && sel_profile_count < MAX_PROFILES; i++) {
				sel_profiles[sel_profile_count++] = profiles_arr->items[i];
			}
		}
	}

	FILE *plan = fopen(out_plan, "w");
	if (!plan) { json_free(proot); json_free(sroot); return 1; }

	int run_count = 0;
	int skipped_missing = 0;
	const char *modes[2];
	int mode_count = 0;
	if (strcmp(mode, "both") == 0) { modes[0] = "paced"; modes[1] = "uncapped"; mode_count = 2; }
	else if (strcmp(mode, "uncapped") == 0) { modes[0] = "uncapped"; mode_count = 1; }
	else { modes[0] = "paced"; mode_count = 1; }

	if (scens_arr && scens_arr->type == JSON_ARR) {
		for (size_t si = 0; si < scens_arr->count; si++) {
			JsonVal *sc = scens_arr->items[si];
			const char *sid = json_str(sc, "id", "");
			if (strcmp(scope, "scenario") == 0 && strcmp(sid, target_id) != 0) continue;

			const char *sname = json_str(sc, "name", sid);
			char rom_path[MAX_PATH_LEN], state_path[MAX_PATH_LEN];
			resolve_pak_path(pak_dir, json_str(sc, "rom", ""), rom_path, sizeof(rom_path));
			resolve_pak_path(pak_dir, json_str(sc, "state", ""), state_path, sizeof(state_path));

			if (!file_exists(rom_path) || (state_path[0] && !file_exists(state_path))) {
				skipped_missing++;
				continue;
			}

			char input_file[MAX_PATH_LEN];
			snprintf(input_file, sizeof(input_file), "%s/inputs_%s.txt", work_dir, sid);
			write_scenario_inputs(sc, input_file);

			int warmup = (int)json_num(sc, "warmup_frames", def_warmup);
			int paced_s = (int)json_num(sc, "paced_seconds", def_paced);
			int uncapped_s = (int)json_num(sc, "uncapped_seconds", def_uncapped);
			int target_fps = (int)json_num(sc, "target_game_fps", 30);

			for (int pi = 0; pi < sel_profile_count; pi++) {
				JsonVal *pr = sel_profiles[pi];
				const char *pid = json_str(pr, "id", "");
				const char *plabel = json_str(pr, "label", pid);
				const char *core_file = json_str(pr, "core", "");
				const char *renderer = json_str(pr, "renderer", "");
				const char *res = json_str(pr, "resolution", "");

				char core_path[MAX_PATH_LEN];
				snprintf(core_path, sizeof(core_path), "%s/cores/%s/%s", pak_dir, platform, core_file);
				if (!file_exists(core_path)) continue;

				char cfg_file[MAX_PATH_LEN];
				snprintf(cfg_file, sizeof(cfg_file), "%s/cfg_%s.cfg", work_dir, pid);
				write_profile_cfg(pr, cfg_file);

				for (int mi = 0; mi < mode_count; mi++) {
					const char *m = modes[mi];
					int dur = (strcmp(m, "uncapped") == 0) ? uncapped_s : paced_s;
					char run_id[MAX_STR_LEN];
					snprintf(run_id, sizeof(run_id), "%s__%s__%s", sid, pid, m);

					fprintf(plan, "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%d\t%d\t%d\t%s\t%s\n",
						run_id, sid, sname, pid, plabel, core_file, core_path, renderer, res, m,
						rom_path, state_path, warmup, dur, target_fps, cfg_file, input_file);
					run_count++;
				}
			}
		}
	}

	fclose(plan);
	json_free(proot);
	json_free(sroot);
	printf("PLANNED=%d SKIPPED_SCENARIOS=%d\n", run_count, skipped_missing);
	return 0;
}

/*
 * aggregate <plan.tsv> <results_dir> <platform> <device_name> <out_summary.json> <out_summary.csv> <out_summary.txt>
 */
static int cmd_aggregate(int argc, char **argv) {
	if (argc < 9) {
		fprintf(stderr, "Usage: benchctl aggregate <plan.tsv> <results_dir> <platform> <device_name> <out_summary.json> <out_summary.csv> <out_summary.txt>\n");
		return 1;
	}
	const char *plan_path = argv[2];
	const char *results_dir = argv[3];
	const char *platform = argv[4];
	const char *device_name = argv[5];
	const char *out_json = argv[6];
	const char *out_csv = argv[7];
	const char *out_txt = argv[8];

	FILE *plan = fopen(plan_path, "r");
	if (!plan) return 1;

	char gov[64], max_freq[64], kernel[128];
	read_sysfs_line("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", gov, sizeof(gov), "unknown");
	read_sysfs_line("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", max_freq, sizeof(max_freq), "0");
	read_sysfs_line("/proc/sys/kernel/osrelease", kernel, sizeof(kernel), "unknown");

	time_t now = time(NULL);
	struct tm *tm_info = gmtime(&now);
	char ts_iso[64];
	strftime(ts_iso, sizeof(ts_iso), "%Y-%m-%dT%H:%M:%SZ", tm_info);

	FILE *jfp = fopen(out_json, "w");
	FILE *cfp = fopen(out_csv, "w");
	FILE *tfp = fopen(out_txt, "w");
	if (!jfp || !cfp || !tfp) {
		if (jfp) fclose(jfp);
		if (cfp) fclose(cfp);
		if (tfp) fclose(tfp);
		fclose(plan);
		return 1;
	}

	fprintf(jfp, "{\n");
	fprintf(jfp, "  \"schema_version\": 1,\n");
	fprintf(jfp, "  \"timestamp_utc\": "); json_write_escaped(jfp, ts_iso); fprintf(jfp, ",\n");
	fprintf(jfp, "  \"platform\": "); json_write_escaped(jfp, platform); fprintf(jfp, ",\n");
	fprintf(jfp, "  \"device\": "); json_write_escaped(jfp, device_name); fprintf(jfp, ",\n");
	fprintf(jfp, "  \"cpu_governor\": "); json_write_escaped(jfp, gov); fprintf(jfp, ",\n");
	fprintf(jfp, "  \"cpu_max_khz\": %s,\n", max_freq[0] ? max_freq : "0");
	fprintf(jfp, "  \"kernel\": "); json_write_escaped(jfp, kernel); fprintf(jfp, ",\n");
	fprintf(jfp, "  \"runs\": [\n");

	fprintf(cfp, "platform,device,run_id,scenario_id,scenario_name,profile_id,profile_label,core,core_sha256,renderer,resolution,mode,status,target_game_fps,vi_fps_avg,rendered_fps_avg,speed_pct,frame_ms_avg,frame_ms_p50,frame_ms_p95,frame_ms_p99,frame_ms_max,fps_1pct_low,fps_01pct_low,missed_vsyncs,audio_underruns,soc_temp_start_c,soc_temp_end_c\n");
	fprintf(tfp, "N64Bench Summary (%s / %s)\n\n", platform, device_name);

	char line[4096];
	int first = 1;
	int completed = 0;
	while (fgets(line, sizeof(line), plan)) {
		size_t ln = strlen(line);
		while (ln > 0 && (line[ln-1] == '\n' || line[ln-1] == '\r')) line[--ln] = '\0';
		if (ln == 0) continue;

		char *cols[17] = {0};
		int ci = 0;
		char *p = line;
		while (ci < 17) {
			cols[ci++] = p;
			char *tab = strchr(p, '\t');
			if (!tab) break;
			*tab = '\0';
			p = tab + 1;
		}
		if (ci < 15) continue;

		const char *run_id = cols[0];
		const char *sid = cols[1];
		const char *sname = cols[2];
		const char *pid = cols[3];
		const char *plabel = cols[4];
		const char *core_file = cols[5];
		const char *core_path = cols[6];
		const char *renderer = cols[7];
		const char *res = cols[8];
		const char *mode = cols[9];
		int target_fps = atoi(cols[14]);

		char run_json_path[MAX_PATH_LEN];
		snprintf(run_json_path, sizeof(run_json_path), "%s/runs/%s.json", results_dir, run_id);
		JsonVal *r = json_load_file(run_json_path);
		if (!r) continue;

		char sha[65];
		sha256_file_hex(core_path, sha);

		const char *status = json_str(r, "status", "unknown");
		double vi_fps = json_num(r, "vi_fps_avg", 0.0);
		double ren_fps = json_num(r, "rendered_fps_avg", 0.0);
		double speed_pct = json_num(r, "speed_pct", 0.0);
		double ms_avg = json_num(r, "frame_ms_avg", 0.0);
		double ms_p50 = json_num(r, "frame_ms_p50", 0.0);
		double ms_p95 = json_num(r, "frame_ms_p95", 0.0);
		double ms_p99 = json_num(r, "frame_ms_p99", 0.0);
		double ms_max = json_num(r, "frame_ms_max", 0.0);
		double low1 = json_num(r, "fps_1pct_low", 0.0);
		double low01 = json_num(r, "fps_01pct_low", 0.0);
		int missed = (int)json_num(r, "missed_vsyncs", 0);
		int underruns = (int)json_num(r, "audio_underruns", 0);
		double t0 = json_num(r, "soc_temp_start_c", -1.0);
		double t1 = json_num(r, "soc_temp_end_c", -1.0);

		if (!first) fprintf(jfp, ",\n");
		first = 0;

		fprintf(jfp, "    {\n");
		fprintf(jfp, "      \"run_id\": "); json_write_escaped(jfp, run_id); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"scenario_id\": "); json_write_escaped(jfp, sid); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"scenario_name\": "); json_write_escaped(jfp, sname); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"profile_id\": "); json_write_escaped(jfp, pid); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"profile_label\": "); json_write_escaped(jfp, plabel); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"core\": "); json_write_escaped(jfp, core_file); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"core_sha256\": "); json_write_escaped(jfp, sha); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"renderer\": "); json_write_escaped(jfp, renderer); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"resolution\": "); json_write_escaped(jfp, res); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"mode\": "); json_write_escaped(jfp, mode); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"status\": "); json_write_escaped(jfp, status); fprintf(jfp, ",\n");
		fprintf(jfp, "      \"target_game_fps\": %d,\n", target_fps);
		fprintf(jfp, "      \"vi_fps_avg\": %.3f,\n", vi_fps);
		fprintf(jfp, "      \"rendered_fps_avg\": %.3f,\n", ren_fps);
		fprintf(jfp, "      \"speed_pct\": %.2f,\n", speed_pct);
		fprintf(jfp, "      \"frame_ms_avg\": %.3f,\n", ms_avg);
		fprintf(jfp, "      \"frame_ms_p50\": %.3f,\n", ms_p50);
		fprintf(jfp, "      \"frame_ms_p95\": %.3f,\n", ms_p95);
		fprintf(jfp, "      \"frame_ms_p99\": %.3f,\n", ms_p99);
		fprintf(jfp, "      \"frame_ms_max\": %.3f,\n", ms_max);
		fprintf(jfp, "      \"fps_1pct_low\": %.3f,\n", low1);
		fprintf(jfp, "      \"fps_01pct_low\": %.3f,\n", low01);
		fprintf(jfp, "      \"missed_vsyncs\": %d,\n", missed);
		fprintf(jfp, "      \"audio_underruns\": %d,\n", underruns);
		fprintf(jfp, "      \"soc_temp_start_c\": %.2f,\n", t0);
		fprintf(jfp, "      \"soc_temp_end_c\": %.2f,\n", t1);
		fprintf(jfp, "      \"frames_csv\": \"frames/%s.csv\"\n", run_id);
		fprintf(jfp, "    }");

		fprintf(cfp, "%s,%s,%s,%s,\"%s\",%s,\"%s\",%s,%s,%s,%s,%s,%s,%d,%.3f,%.3f,%.2f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%d,%d,%.2f,%.2f\n",
			platform, device_name, run_id, sid, sname, pid, plabel, core_file, sha, renderer, res, mode, status,
			target_fps, vi_fps, ren_fps, speed_pct, ms_avg, ms_p50, ms_p95, ms_p99, ms_max, low1, low01, missed, underruns, t0, t1);

		if (strcmp(mode, "uncapped") == 0) {
			fprintf(tfp, "%s [%s] UNCAPPED: %.1f VI/s (%.0f%% speed) | 3D: %.1f fps\n",
				sid, plabel, vi_fps, speed_pct, ren_fps);
		}
		else {
			fprintf(tfp, "%s [%s] PACED: %.1f VI/s (1%% low %.1f) | 3D: %.1f fps | miss:%d\n",
				sid, plabel, vi_fps, low1, ren_fps, missed);
		}

		json_free(r);
		completed++;
	}

	fprintf(jfp, "\n  ]\n}\n");
	if (completed == 0) {
		fprintf(tfp, "No completed benchmark runs.\n");
	}

	fclose(jfp);
	fclose(cfp);
	fclose(tfp);
	fclose(plan);
	printf("AGGREGATED=%d\n", completed);
	return 0;
}

int main(int argc, char **argv) {
	if (argc < 2) {
		fprintf(stderr, "Usage: benchctl <list-tiers|list-profiles|list-scenarios|plan|aggregate> ...\n");
		return 1;
	}
	if (strcmp(argv[1], "list-tiers") == 0 && argc >= 4)
		return cmd_list_tiers(argv[2], argv[3]);
	if (strcmp(argv[1], "list-profiles") == 0 && argc >= 4)
		return cmd_list_profiles(argv[2], argv[3]);
	if (strcmp(argv[1], "list-scenarios") == 0 && argc >= 5)
		return cmd_list_scenarios(argv[2], argv[3], argv[4]);
	if (strcmp(argv[1], "plan") == 0)
		return cmd_plan(argc, argv);
	if (strcmp(argv[1], "aggregate") == 0)
		return cmd_aggregate(argc, argv);

	fprintf(stderr, "Unknown command or missing args: %s\n", argv[1]);
	return 1;
}

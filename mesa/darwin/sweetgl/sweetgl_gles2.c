/*
 * Copyright © 2026 ios-jasmine
 * SPDX-License-Identifier: MIT
 *
 * The public GL ES 2/3 entry points (glClear, ...) for sweetgl, as
 * libGLESv2 has them: each one calls through the current context's dispatch
 * table (C version; see src/mesa/glapi/es2api/libgles2_public.c).
 */

#include "glapi/glapi_priv.h"

#define MAPI_TMP_DEFINES
#define MAPI_TMP_PUBLIC_ENTRIES_NO_HIDDEN
#include "es2_glapi_mapi_tmp.h"

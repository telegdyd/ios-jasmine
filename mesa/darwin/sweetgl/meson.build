# Copyright © 2026 ios-jasmine
# SPDX-License-Identifier: MIT

# sweetgl: GL ES contexts on the freedreno screen without EGL or DRI

sweetgl_es2_mapi_tmp_h = custom_target(
  'es2_glapi_mapi_tmp.h',
  input : ['../../../mesa/glapi/new/gen_gldispatch_mapi.py', '../../../mesa/glapi/glapi/registry/gl.xml'],
  output : 'es2_glapi_mapi_tmp.h',
  command : [prog_python, '@INPUT0@', 'glesv2', '@INPUT1@'],
  depend_files : glapi_xml_py_deps,
  capture : true,
)

libsweetgl = static_library(
  'sweetgl',
  ['sweetgl.c', 'sweetgl.h', 'sweetgl_gles2.c', sweetgl_es2_mapi_tmp_h],
  include_directories : [
    inc_include, inc_util, inc_mesa, inc_src, inc_gallium, inc_gallium_aux, inc_freedreno,
    include_directories('../../drivers/freedreno'),
    include_directories('../../drivers/freedreno/ir3', '../../../freedreno/drm'),
  ],
  dependencies : [idep_mesautil, idep_xmlconfig, idep_nir],
  link_with : [libmesa, libglapi],
  gnu_symbol_visibility : 'hidden',
)

# the GL ES test: GLSL ES shaders, textures, blending and depth through GL calls,
# and on iOS rendering into and sampling from IOSurfaces
sweetgl_test_deps = [idep_nir, idep_mesautil, idep_u_tracepoints, idep_xmlconfig]
if host_machine.system() == 'darwin'
  sweetgl_test_deps += dependency('appleframeworks', modules : ['IOSurface', 'CoreFoundation'])
endif
sweetgpu_gltest = executable(
  'sweetgpu_gltest',
  [
    'sweetgpu_gltest.c',
    # freedreno references renderonly (KMS scanout buffers, unused here)
    '../../auxiliary/renderonly/renderonly.c',
    freedreno_tracepoints[1],
    freedreno_xml_header_files,
  ],
  include_directories : [inc_include, inc_util, inc_gallium, inc_gallium_aux],
  dependencies : sweetgl_test_deps,
  link_with : [
    libsweetgl,
    libmesa,
    libglapi,
    libfreedreno,
    libfreedreno_drm,
    libfreedreno_ir2,
    libfreedreno_ir3,
    libfreedreno_layout,
    libgallium,
    libfreedreno_perfcntrs,
  ],
  install : false,
)

# libsweetca: sweetgl plus an EAGL layer that gives CoreAnimation's GLES renderer a
# GLI dispatch table over Mesa (sweetca.c); sweetca_test links it
if host_machine.system() == 'darwin'
  libsweetca = shared_library(
    'sweetca',
    [
      'sweetca.c',
      '../../auxiliary/renderonly/renderonly.c',
      freedreno_tracepoints[1],
      freedreno_xml_header_files,
    ],
    include_directories : [inc_include, inc_util, inc_gallium, inc_gallium_aux],
    dependencies : sweetgl_test_deps + [
      dependency('appleframeworks', modules : ['OpenGLES', 'IOSurface', 'CoreFoundation']),
    ],
    link_with : [
      libsweetgl,
      libmesa,
      libglapi,
      libfreedreno,
      libfreedreno_drm,
      libfreedreno_ir2,
      libfreedreno_ir3,
      libfreedreno_layout,
      libgallium,
      libfreedreno_perfcntrs,
    ],
    link_args : ['-Wl,-install_name,@executable_path/libsweetca.dylib'],
    install : false,
  )
endif

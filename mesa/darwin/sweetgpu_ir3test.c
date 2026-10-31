/* Copyright (c) 2026 ios-jasmine contributors
 * SPDX-License-Identifier: MIT
 * Step 2: exercise AIR-equivalent NIR on a512 without a Metal runtime.
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "pipe/p_context.h"
#include "pipe/p_screen.h"
#include "pipe/p_state.h"
#include "compiler/nir/nir_builder.h"
#include "util/u_inlines.h"
#include "util/driconf.h"
#include "util/xmlconfig.h"
#include "freedreno_screen.h"
static const driOptionDescription fd_driconf[] = {
#include "pipe-loader/driinfo_gallium.h"
#include "driinfo_freedreno.h"
};
#define SIZE 1024
#define THREADS 32
static const uint32_t values[] = {0xffffffff,0xffffff80,0x01000001,0x01000003,
   0x7fffffff,0x00ffffff,0x80000001,0xfeffffff};
int main(int argc, char **argv)
{
   setvbuf(stdout,NULL,_IONBF,0);
   if (argc != 2) { puts("usage: sweetgpu_ir3test u2f|rtne|rtz|negative|load8|load16|store8|store16"); return 2; }
   const char *mode=argv[1];
   bool rounding=!strcmp(mode,"u2f") || !strcmp(mode,"rtne") || !strcmp(mode,"rtz");
   bool negative=!strcmp(mode,"negative");
   bool load=!strcmp(mode,"load8") || !strcmp(mode,"load16");
   bool store=!strcmp(mode,"store8") || !strcmp(mode,"store16");
   if (!rounding && !negative && !load && !store) return 2;
   unsigned bits=strstr(mode,"16") ? 16 : 8;
   glsl_type_singleton_init_or_ref();
   driOptionCache options,info;
   driParseOptionInfo(&info,fd_driconf,ARRAY_SIZE(fd_driconf));
   driParseOptionInfo(&options,fd_driconf,ARRAY_SIZE(fd_driconf));
   struct pipe_screen_config config={.options=&options,.options_info=&info};
   int fd=open("/dev/null",O_RDWR);
   struct pipe_screen *screen=fd_screen_create(fd,&config,NULL);
   if (!screen) { puts("FAIL: no screen"); return 1; }
   printf("%s: %s\n",mode,screen->get_name(screen));
   struct pipe_context *pipe=screen->context_create(screen,NULL,0);
   if (!pipe) return 1;
   uint8_t input[SIZE],expected[SIZE],result[SIZE];
   memset(expected,0xa5,SIZE);
   for (unsigned i=0;i<SIZE;i++) input[i]=(i*37+11)&255;
   if (rounding) for (unsigned i=0;i<THREADS;i++) memcpy(input+i*4,&values[i%ARRAY_SIZE(values)],4);
   for (unsigned i=0;i<THREADS;i++) {
      if (rounding) {
         uint32_t u; memcpy(&u,input+i*4,4);
         volatile uint32_t vu=u; volatile int32_t vi=(int32_t)u;
         float uf=(float)vu,sf=(float)vi;
         if (!strcmp(mode,"rtz")) {
            // Compute exact round-toward-zero from the nearest float result.
            uint32_t raw;
            if ((double)uf>(double)u) { memcpy(&raw,&uf,4); --raw; memcpy(&uf,&raw,4); }
            if ((double)sf>(double)vi && vi>0) { memcpy(&raw,&sf,4); --raw; memcpy(&sf,&raw,4); }
            if ((double)sf<(double)vi && vi<0) { memcpy(&raw,&sf,4); --raw; memcpy(&sf,&raw,4); }
         }
         memcpy(expected+i*8,&uf,4); memcpy(expected+i*8+4,&sf,4);
      } else if (negative) memcpy(expected+i*4,input+(i+1)*24-4,4);
      else if (load) { uint32_t v=0; memcpy(&v,input+(i+1)*(bits/8),bits/8); memcpy(expected+i*4,&v,4); }
      else { uint32_t v=i*7+3; memcpy(expected+64+i*(bits/8),&v,bits/8); }
   }
   struct pipe_resource *resources[2];
   resources[0]=pipe_buffer_create_with_data(pipe,PIPE_BIND_SHADER_BUFFER,PIPE_USAGE_DEFAULT,SIZE,(uint8_t[SIZE]){0});
   resources[1]=pipe_buffer_create_with_data(pipe,PIPE_BIND_SHADER_BUFFER,PIPE_USAGE_DEFAULT,SIZE,input);
   if (!resources[0] || !resources[1]) return 1;
   uint8_t initial[SIZE]; memset(initial,0xa5,SIZE);
   pipe_buffer_write(pipe,resources[0],0,SIZE,initial);
   struct pipe_shader_buffer buffers[2]={{.buffer=resources[0],.buffer_size=SIZE},{.buffer=resources[1],.buffer_size=SIZE}};
   pipe->set_shader_buffers(pipe,MESA_SHADER_COMPUTE,0,2,buffers,1);
   nir_builder b=nir_builder_init_simple_shader(MESA_SHADER_COMPUTE,screen->nir_options[MESA_SHADER_COMPUTE],"jasmine-step2-%s",mode);
   b.shader->info.workgroup_size[0]=THREADS; b.shader->info.workgroup_size[1]=1; b.shader->info.workgroup_size[2]=1;
   b.shader->info.num_ssbos=2;
   if (!strcmp(mode,"rtne")) b.shader->info.float_controls_execution_mode=FLOAT_CONTROLS_ROUNDING_MODE_RTE_FP32;
   if (!strcmp(mode,"rtz")) b.shader->info.float_controls_execution_mode=FLOAT_CONTROLS_ROUNDING_MODE_RTZ_FP32;
   nir_def *id=nir_channel(&b,nir_load_local_invocation_id(&b),0),*zero=nir_imm_int(&b,0),*one=nir_imm_int(&b,1);
   nir_def *offset=nir_imul_imm(&b,id,4),*v;
   if (rounding) {
      v=nir_load_ssbo(&b,1,32,one,offset,.align_mul=4);
      nir_store_ssbo(&b,nir_u2f32(&b,v),zero,nir_imul_imm(&b,id,8),.write_mask=1,.align_mul=4);
      nir_store_ssbo(&b,nir_i2f32(&b,v),zero,nir_iadd_imm(&b,nir_imul_imm(&b,id,8),4),.write_mask=1,.align_mul=4);
   } else if (negative) {
      nir_def *off=nir_iadd_imm(&b,nir_imul_imm(&b,nir_iadd_imm(&b,id,1),24),-4);
      v=nir_load_ssbo(&b,1,32,one,off,.align_mul=4);
      nir_store_ssbo(&b,v,zero,offset,.write_mask=1,.align_mul=4);
   } else if (load) {
      v=nir_load_ssbo(&b,1,bits,one,nir_imul_imm(&b,nir_iadd_imm(&b,id,1),bits/8),.align_mul=bits/8);
      nir_store_ssbo(&b,nir_u2u32(&b,v),zero,offset,.write_mask=1,.align_mul=4);
   } else {
      v=nir_u2uN(&b,nir_iadd_imm(&b,nir_imul_imm(&b,id,7),3),bits);
      nir_store_ssbo(&b,v,zero,nir_iadd_imm(&b,nir_imul_imm(&b,id,bits/8),64),.write_mask=1,.align_mul=bits/8);
   }
   nir_validate_shader(b.shader,"step2 input");
   screen->finalize_nir(screen,b.shader,true);
   puts("step: compile");
   struct pipe_compute_state state={.ir_type=PIPE_SHADER_IR_NIR,.prog=b.shader};
   void *cs=pipe->create_compute_state(pipe,&state);
   if (!cs) { puts("FAIL: compile"); return 1; }
   pipe->bind_compute_state(pipe,cs);
   struct pipe_grid_info grid={.work_dim=1,.block={THREADS,1,1},.grid={1,1,1}};
   puts("step: launch"); pipe->launch_grid(pipe,&grid);
   pipe->memory_barrier(pipe,PIPE_BARRIER_ALL);
   struct pipe_fence_handle *fence=NULL;
   pipe->flush(pipe,&fence,0);
   bool done=fence && screen->fence_finish(screen,NULL,fence,5ull*1000*1000*1000);
   screen->fence_reference(screen,&fence,NULL);
   if (!done) { puts("FAIL: fence timeout"); return 1; }
   pipe_buffer_read(pipe,resources[0],0,SIZE,result);
   unsigned bad=0;
   for (unsigned i=0;i<SIZE;i++) if (result[i]!=expected[i]) {
      if (bad<16) printf("byte %u: %02x expected %02x\n",i,result[i],expected[i]);
      ++bad;
   }
   printf("%s: %s: %u of %u bytes wrong (includes guard bytes)\n",bad?"FAIL":"PASS",mode,bad,SIZE);
   pipe->bind_compute_state(pipe,NULL); pipe->delete_compute_state(pipe,cs);
   pipe->set_shader_buffers(pipe,MESA_SHADER_COMPUTE,0,2,NULL,0);
   for (unsigned i=0;i<2;i++) pipe_resource_reference(&resources[i],NULL);
   pipe->destroy(pipe); screen->destroy(screen); close(fd);
   driDestroyOptionCache(&options); driDestroyOptionInfo(&info);
   glsl_type_singleton_decref();
   return bad?1:0;
}

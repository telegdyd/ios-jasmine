/* SPDX-License-Identifier: MIT
 * Real GPU reference tests for the Task 24 experiment. Included after the
 * IOSurface helpers. Each feedback draw reads its own pixel once; a barrier
 * precedes every such draw. Readback happens only after a sequence, so it
 * cannot accidentally supply the ordering being tested between draws.
 */
static uint8_t feedback_base[4];
static unsigned feedback_steps;
static bool feedback_partial;

static bool
feedback_expected(unsigned x, unsigned y, uint8_t out[4])
{
   memcpy(out, feedback_base, 4);
   if (!feedback_partial || (x >= 16 && x < 48 && y >= 16 && y < 48)) {
      out[0] += 4 * feedback_steps;
      out[1] += 2 * feedback_steps;
      out[2] += feedback_steps;
   }
   return true;
}

static void
feedback_solid(GLuint solid, unsigned r, unsigned g, unsigned b)
{
   glDisable(GL_SCISSOR_TEST);
   glUseProgram(solid);
   glUniform4f(glGetUniformLocation(solid, "color"), r / 255.0f, g / 255.0f, b / 255.0f, 1);
   glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

static void
feedback_draws(GLuint program, GLuint texture, unsigned count)
{
   glUseProgram(program);
   glBindTexture(GL_TEXTURE_2D, texture);
   glUniform1i(glGetUniformLocation(program, "tex"), 0);
   for (unsigned i = 0; i < count; i++) {
      sgl_texture_barrier();
      glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
   }
}

static bool
feedback_check(const char *name, unsigned r, unsigned g, unsigned b,
               unsigned steps, bool partial)
{
   feedback_base[0] = r;
   feedback_base[1] = g;
   feedback_base[2] = b;
   feedback_base[3] = 255;
   feedback_steps = steps;
   feedback_partial = partial;
   read_back();
   return check(name, feedback_expected, 1);
}

/* Separate diagnostic controls. Never insert these waits/readbacks into the
 * acceptance sequence below: a control can hide exactly the bug it diagnoses.
 */
static bool
feedback_diagnostic_target(const char *kind, GLuint solid, GLuint sample,
                           const GLuint textures[3], const GLuint fbos[2])
{
   bool ok = true;
   char name[128];
   glBindFramebuffer(GL_FRAMEBUFFER, fbos[0]);
   glDisable(GL_SCISSOR_TEST);
   glClearColor(32 / 255.0f, 64 / 255.0f, 96 / 255.0f, 1);
   glClear(GL_COLOR_BUFFER_BIT);
   snprintf(name, sizeof(name), "diagnostic %s clear only", kind);
   ok &= feedback_check(name, 32, 64, 96, 0, false);

   /* Draw->clear, clear->sample and feedback->clear, then controls which
    * complete before/after clear or replace only clear with a solid draw.
    */
   for (unsigned variant = 0; variant < 6; variant++) {
      feedback_solid(solid, 16, 32, 64);
      if (variant >= 2)
         feedback_draws(sample, textures[0], 2);
      if (variant == 3)
         glFinish();
      if (variant == 5) {
         feedback_solid(solid, 32, 64, 96);
      } else {
         glClearColor(32 / 255.0f, 64 / 255.0f, 96 / 255.0f, 1);
         glClear(GL_COLOR_BUFFER_BIT);
      }
      if (variant == 4)
         glFinish();
      if (variant >= 1) {
         glEnable(GL_SCISSOR_TEST);
         glScissor(16, 16, 32, 32);
         feedback_draws(sample, textures[0], 3);
      }
      static const char *labels[] = {
         "draw then clear", "clear then sample", "feedback then clear then sample",
         "finish before clear control", "finish after clear control", "solid replaces clear control",
      };
      snprintf(name, sizeof(name), "diagnostic %s %s", kind, labels[variant]);
      ok &= feedback_check(name, 32, 64, 96, variant ? 3 : 0, variant != 0);
   }

   /* The final switch/revisit is identical across alias/same-name controls.
    * The checkpoint variant intentionally reads the target BEFORE sampling
    * its alias; it tells us whether the old patch already exists at that point.
    */
   for (unsigned variant = 0; variant < 3; variant++) {
      glBindFramebuffer(GL_FRAMEBUFFER, fbos[0]);
      feedback_solid(solid, 48, 80, 112);
      glBindFramebuffer(GL_FRAMEBUFFER, fbos[1]);
      feedback_solid(solid, 24, 40, 56);
      glBindFramebuffer(GL_FRAMEBUFFER, fbos[0]);
      if (variant == 2) {
         snprintf(name, sizeof(name), "diagnostic %s before alias checkpoint", kind);
         ok &= feedback_check(name, 48, 80, 112, 0, false);
      }
      feedback_draws(sample, textures[variant ? 2 : 0], 3);
      glBindFramebuffer(GL_FRAMEBUFFER, fbos[1]);
      feedback_draws(sample, textures[1], 2);
      glBindFramebuffer(GL_FRAMEBUFFER, fbos[0]);
      feedback_draws(sample, textures[0], 2);
      snprintf(name, sizeof(name), "diagnostic %s revisit %s", kind,
               variant == 0 ? "same texture name" : variant == 1 ? "alias" : "alias after checkpoint control");
      ok &= feedback_check(name, 48, 80, 112, 5, false);
      glBindFramebuffer(GL_FRAMEBUFFER, fbos[1]);
      snprintf(name, sizeof(name), "diagnostic %s other target variant %u", kind, variant);
      ok &= feedback_check(name, 24, 40, 56, 2, false);
   }
   return ok;
}

static bool
feedback(struct sgl_context *ctx, bool diagnostic)
{
   uint32_t pitch[2];
   IOSurfaceRef surfaces[2] = {iosurface_new(&pitch[0]), iosurface_new(&pitch[1])};
   if (!surfaces[0] || !surfaces[1]) {
      if (surfaces[0]) CFRelease(surfaces[0]);
      if (surfaces[1]) CFRelease(surfaces[1]);
      return false;
   }
   GLuint textures[3], fbos[2];
   glGenTextures(3, textures);
   glGenFramebuffers(2, fbos);
   bool ok = true;
   glActiveTexture(GL_TEXTURE0);
   for (unsigned i = 0; i < 3; i++) {
      unsigned surface = i == 1 ? 1 : 0; /* texture2 aliases texture0's IOSurface */
      glBindTexture(GL_TEXTURE_2D, textures[i]);
      ok &= sgl_tex_image_iosurface(ctx, GL_TEXTURE_2D, IOSurfaceGetID(surfaces[surface]),
                                   W, H, pitch[surface], SGL_IOSURFACE_BGRA);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
      if (i < 2) {
         glBindFramebuffer(GL_FRAMEBUFFER, fbos[i]);
         glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, textures[i], 0);
         ok &= glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
      }
   }
   const char *vs = "attribute vec2 pos; void main() {gl_Position=vec4(pos,0.,1.);}";
   GLuint solid = program(vs, "precision highp float; uniform vec4 color; void main(){gl_FragColor=color;}");
   GLuint sample = program(vs, "precision highp float; uniform sampler2D tex; void main(){"
                              "gl_FragColor=texture2D(tex,gl_FragCoord.xy/vec2(64.,64.))"
                              "+vec4(4./255.,2./255.,1./255.,0.);}");
   const float quad[] = {-1,-1, 1,-1, -1,1, 1,1};
   glBindBuffer(GL_ARRAY_BUFFER, 0);
   glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad);
   glEnableVertexAttribArray(0);
   glDisableVertexAttribArray(1);
   glDisable(GL_BLEND);
   glDisable(GL_DEPTH_TEST);
   glDisable(GL_STENCIL_TEST);
   glDisable(GL_SCISSOR_TEST);
   glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
   glViewport(0, 0, W, H);

   if (diagnostic) {
      ok &= feedback_diagnostic_target("imported", solid, sample, textures, fbos);
      /* Ordinary GL allocations are a separate control for the imported
       * linear path. Their third name is deliberately the first name again,
       * not a claim to exercise independent imported aliases.
       */
      GLuint native_textures[3], native_fbos[2];
      glGenTextures(2, native_textures);
      native_textures[2] = native_textures[0];
      glGenFramebuffers(2, native_fbos);
      for (unsigned i = 0; i < 2; i++) {
         glBindTexture(GL_TEXTURE_2D, native_textures[i]);
         glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
         glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
         glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
         glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
         glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
         glBindFramebuffer(GL_FRAMEBUFFER, native_fbos[i]);
         glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, native_textures[i], 0);
         ok &= glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
      }
      ok &= feedback_diagnostic_target("GL allocation (no imported alias)", solid, sample,
                                       native_textures, native_fbos);
      glBindFramebuffer(GL_FRAMEBUFFER, 0);
      glDeleteFramebuffers(2, native_fbos);
      glDeleteTextures(2, native_textures);
      goto cleanup;
   }

   glBindFramebuffer(GL_FRAMEBUFFER, fbos[0]);
   feedback_solid(solid, 16, 32, 64);
   feedback_draws(sample, textures[0], 8);
   ok &= feedback_check("feedback repeated eight draws", 16, 32, 64, 8, false);

   /* Clear follows retained feedback without an intervening read/finish. */
   feedback_solid(solid, 16, 32, 64);
   feedback_draws(sample, textures[0], 2);
   glClearColor(32 / 255.0f, 64 / 255.0f, 96 / 255.0f, 1);
   glClear(GL_COLOR_BUFFER_BIT);
   glEnable(GL_SCISSOR_TEST);
   glScissor(16, 16, 32, 32);
   feedback_draws(sample, textures[0], 3);
   ok &= feedback_check("feedback clear and partial scissor", 32, 64, 96, 3, true);

   /* Stage 2: a batch that starts with a (fast) clear and a draw that leaves
    * the target unchanged (blend ZERO, ONE), then more feedback draws than
    * patch 0008's narrow limit of five, so the widened path retains barriers
    * in a cleared batch past that limit (the first barrier needs a draw).
    */
   glDisable(GL_SCISSOR_TEST);
   glClearColor(40 / 255.0f, 24 / 255.0f, 8 / 255.0f, 1);
   glClear(GL_COLOR_BUFFER_BIT);
   glEnable(GL_BLEND);
   glBlendFunc(GL_ZERO, GL_ONE);
   feedback_solid(solid, 200, 200, 200);
   glDisable(GL_BLEND);
   feedback_draws(sample, textures[0], 7);
   ok &= feedback_check("feedback after first-in-batch clear, seven draws", 40, 24, 8, 7, false);

   /* Keep another target pending, then revisit both; use a distinct texture
    * name aliasing the first IOSurface as the sampled input on the first one.
    */
   feedback_solid(solid, 48, 80, 112);
   glBindFramebuffer(GL_FRAMEBUFFER, fbos[1]);
   feedback_solid(solid, 24, 40, 56);
   glBindFramebuffer(GL_FRAMEBUFFER, fbos[0]);
   feedback_draws(sample, textures[2], 3);
   glBindFramebuffer(GL_FRAMEBUFFER, fbos[1]);
   feedback_draws(sample, textures[1], 2);
   glBindFramebuffer(GL_FRAMEBUFFER, fbos[0]);
   feedback_draws(sample, textures[0], 2);
   ok &= feedback_check("feedback target revisit and imported alias", 48, 80, 112, 5, false);
   glBindFramebuffer(GL_FRAMEBUFFER, fbos[1]);
   ok &= feedback_check("feedback other pending target preserved", 24, 40, 56, 2, false);

cleanup:;
   GLenum error = glGetError();
   if (error != GL_NO_ERROR) {
      printf("FAIL: feedback GL error %#x\n", error);
      ok = false;
   }
   glBindFramebuffer(GL_FRAMEBUFFER, 0);
   glUseProgram(0);
   glDisable(GL_SCISSOR_TEST);
   glDisableVertexAttribArray(0);
   glDeleteProgram(solid);
   glDeleteProgram(sample);
   glDeleteFramebuffers(2, fbos);
   glDeleteTextures(3, textures);
   CFRelease(surfaces[0]);
   CFRelease(surfaces[1]);
   return ok;
}

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

static bool
feedback(struct sgl_context *ctx)
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

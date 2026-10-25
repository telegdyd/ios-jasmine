/* Mode 2 only. GL's owner thread edits open; callbacks only publish error.
 * Each batch owns its BOs and a reference to the error state, never sca_ctx.
 */
struct sgl_render_ticket {
   struct fd_bo *bo;
   uint32_t surface;
   uint64_t generation, epoch;
};

struct sgl_render_batch {
   struct sgl_render_set *set;
   struct pipe_context *driver;
   unsigned count;
   struct sgl_render_batch *next;
   struct sgl_render_ticket tickets[32];
};

struct sgl_render_set {
   unsigned refs;
   int error;
   bool cancelled;
   struct sgl_render_batch *open;
   pthread_mutex_t lock;
   struct sgl_render_batch *inflight;
};

static void
sgl_render_unref(struct sgl_render_set *set)
{
   if (__atomic_sub_fetch(&set->refs, 1, __ATOMIC_ACQ_REL) == 0) {
      pthread_mutex_destroy(&set->lock);
      FREE(set);
   }
}

int
sgl_ticket_error(struct sgl_context *ctx)
{
   int error = ctx->tickets ? __atomic_load_n(&ctx->tickets->error, __ATOMIC_ACQUIRE) : 0;
   return error ? error : darwin_pipeline_error();
}

bool
sgl_tickets_available(struct sgl_context *ctx)
{
   uint64_t epoch = 0;
   if (!sgl_driver_pipe(ctx))
      return false;
   uint64_t flags = darwin_ticket_query(fd_screen(ctx->st->pipe->screen)->dev, &epoch);
   if (ctx->tickets && ctx->tickets->open && ctx->tickets->open->count &&
       ctx->tickets->open->tickets[0].epoch != epoch && sgl_ticket_finish(ctx))
      return false;
   return (flags & 15) == 15;
}

int
sgl_ticket_write(struct sgl_context *ctx, uint32_t surface)
{
   int error = sgl_ticket_error(ctx);
   if (error || !surface || !sgl_driver_pipe(ctx))
      return error ? error : -ENOTSUP;
   if (!ctx->tickets) {
      ctx->tickets = CALLOC_STRUCT(sgl_render_set);
      if (!ctx->tickets)
         return -ENOMEM;
      int init = pthread_mutex_init(&ctx->tickets->lock, NULL);
      if (init) {
         FREE(ctx->tickets);
         ctx->tickets = NULL;
         return -ENOMEM;
      }
      ctx->tickets->refs = 1;
   }
   struct sgl_render_set *set = ctx->tickets;
   bool pending = false;
   pthread_mutex_lock(&set->lock);
   for (struct sgl_render_batch *b = set->inflight; b; b = b->next) {
      for (unsigned i = 0; i < b->count; i++)
         pending |= b->tickets[i].surface == surface;
   }
   pthread_mutex_unlock(&set->lock);
   if (pending) {
      /* Reusing an offscreen target can reach us before its previous callback.
       * Wait only at this write hazard, never at the preceding w_Flush. */
      error = sgl_flush_submit(ctx);
      if (error)
         return error;
      error = sgl_ticket_error(ctx);
      if (error)
         return error;
   }
   if (!set->open) {
      set->open = CALLOC_STRUCT(sgl_render_batch);
      if (!set->open)
         return -ENOMEM;
      set->open->set = set;
      set->open->driver = sgl_driver_pipe(ctx);
   }
   struct sgl_render_batch *batch = set->open;
   for (unsigned i = 0; i < batch->count; i++) {
      if (batch->tickets[i].surface == surface)
         return 0;
   }
   if (batch->count == 32)
      return -E2BIG;
   struct fd_device *dev = fd_screen(ctx->st->pipe->screen)->dev;
   struct fd_bo *bo = fd_bo_from_dmabuf(dev, surface);
   if (!bo)
      return -ENOMEM;
   struct sgl_render_ticket ticket = {.bo = bo, .surface = surface};
   error = darwin_ticket_begin(dev, &bo->handle, 1, &ticket.generation, &ticket.epoch);
   if (error) {
      fd_bo_del(bo);
      return error;
   }
   batch->tickets[batch->count++] = ticket;
   return 0;
}

static void
sgl_render_driver(void *data)
{
   struct sgl_render_batch *batch = data;
   /* One-shot bounded S10 fixtures. No hook is active in modes 0/1. */
   static unsigned tested;
   const char *test = getenv("SWEETCA_TICKET_TEST");
   unsigned hook = test && !strcmp(test, "delay80") ? 1 :
                   test && !strcmp(test, "delay150") ? 2 :
                   test && !strcmp(test, "stale") ? 4 :
                   test && !strcmp(test, "abort") ? 8 : 0;
   if (!batch->count)
      hook = 0;
   if (hook && (__atomic_fetch_or(&tested, hook, __ATOMIC_ACQ_REL) & hook))
      hook = 0;
   if (hook == 1 || hook == 2)
      usleep(hook == 1 ? 80000 : 150000);
   struct pipe_context *pipe = batch->driver;
   struct pipe_screen *screen = pipe->screen;
   struct pipe_fence_handle *fence = NULL;
   pipe->flush(pipe, &fence, 0);
   /* This drains the submit queue even if the GPU is still busy. The poll's
    * boolean is not successful-submit proof; use the retained final fence. */
   if (fence)
      (void)screen->fence_finish(screen, pipe, fence, 0);
   struct pipe_fence_handle *final = fence;
   while (final && final->last_fence)
      final = final->last_fence;
   int error = darwin_pipeline_error();
   if (hook == 8)
      error = -ECANCELED;
   if (__atomic_load_n(&batch->set->cancelled, __ATOMIC_ACQUIRE))
      error = -ECANCELED;
   uint32_t seqno = final && final->fence ? final->fence->kfence : 0;
   struct fd_device *dev = batch->count ? batch->tickets[0].bo->dev : NULL;
   if (batch->count && (!seqno || !final || !final->fence || final->fence->pipe->dev != dev))
      error = error ? error : -EIO;
   for (unsigned i = 0; i < batch->count; i++) {
      struct sgl_render_ticket *t = &batch->tickets[i];
      uint64_t epoch = 0;
      uint64_t flags = darwin_ticket_query(t->bo->dev, &epoch);
      bool cancelled = (flags & 1) && epoch != t->epoch;
      int ret = darwin_ticket_end(t->bo->dev, t->generation, t->epoch + (hook == 4 && i == 0), error != 0 || cancelled, seqno);
      if (ret) {
         /* Resolve every open generation even if one SEAL was rejected. */
         int abort = darwin_ticket_end(t->bo->dev, t->generation, t->epoch, true, 0);
         flags = darwin_ticket_query(t->bo->dev, &epoch);
         cancelled = !hook && !abort && (flags & 1) && epoch != t->epoch;
         if (!cancelled)
            error = error ? error : ret;
      }
   }
   if (error) {
      int zero = 0;
      __atomic_compare_exchange_n(&batch->set->error, &zero, error, false,
                                  __ATOMIC_RELEASE, __ATOMIC_RELAXED);
   }
   screen->fence_reference(screen, &fence, NULL);
   pthread_mutex_lock(&batch->set->lock);
   struct sgl_render_batch **p = &batch->set->inflight;
   while (*p && *p != batch)
      p = &(*p)->next;
   if (*p)
      *p = batch->next;
   pthread_mutex_unlock(&batch->set->lock);
   for (unsigned i = 0; i < batch->count; i++)
      fd_bo_del(batch->tickets[i].bo);
   sgl_render_unref(batch->set);
   FREE(batch);
}

int
sgl_ticket_flush(struct sgl_context *ctx)
{
   struct sgl_render_set *set = ctx->tickets;
   if (set && set->open) {
      struct sgl_render_batch *batch = set->open;
      set->open = NULL;
      __atomic_add_fetch(&set->refs, 1, __ATOMIC_RELAXED);
      pthread_mutex_lock(&set->lock);
      batch->next = set->inflight;
      set->inflight = batch;
      pthread_mutex_unlock(&set->lock);
      struct pipe_context *pipe = ctx->st->pipe;
      pipe->callback(pipe, sgl_render_driver, batch, false);
      pipe->flush(pipe, NULL, PIPE_FLUSH_ASYNC);
   }
   return sgl_ticket_error(ctx);
}

int
sgl_ticket_finish(struct sgl_context *ctx)
{
   int error = sgl_ticket_flush(ctx);
   int drain = sgl_flush_submit(ctx);
   return error ? error : drain ? drain : sgl_ticket_error(ctx);
}

static void
sgl_tickets_destroy(struct sgl_context *ctx)
{
   if (!ctx->tickets)
      return;
   __atomic_store_n(&ctx->tickets->cancelled, true, __ATOMIC_RELEASE);
   /* TC destruction drains these callbacks before destroying the driver pipe. */
   (void)sgl_ticket_flush(ctx);
   sgl_render_unref(ctx->tickets);
   ctx->tickets = NULL;
}

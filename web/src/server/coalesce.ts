/** Sends one request at a time: values that arrive while one is out wait, merged (by
 * default the newest wins), so a slider dragged fast sends its latest value, not every
 * one. `busy()` says whether anything is out or waiting. */
export function coalesce<T>(
  send: (value: T) => Promise<unknown>,
  onError: (e: Error) => void,
  merge: (queued: T, next: T) => T = (_, next) => next,
): { push: (value: T) => Promise<void>; busy: () => boolean } {
  let sending = false;
  let queued: { value: T } | null = null;
  return {
    busy: () => sending || queued !== null,
    async push(value: T) {
      queued = { value: queued ? merge(queued.value, value) : value };
      if (sending) return;
      sending = true;
      while (queued) {
        const { value: v } = queued;
        queued = null;
        try {
          await send(v);
        } catch (e) {
          onError(e as Error);
        }
      }
      sending = false;
    },
  };
}

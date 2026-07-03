import { useCallback, useEffect, useState } from 'react'

/** Local editable copy of a server config with dirty tracking.
 *
 * The draft initializes once the server data arrives and is re-initialized
 * after a save via clear() — the refetched file content (post-validation,
 * post-pruning) becomes the new baseline, so the form always mirrors what's
 * actually on disk.
 */
export function useDraft<T>(server: T | null | undefined) {
  const [draft, setDraft] = useState<T | null>(null)
  const [baseline, setBaseline] = useState<string>('')

  useEffect(() => {
    if (server != null && draft === null) {
      setDraft(structuredClone(server))
      setBaseline(JSON.stringify(server))
    }
  }, [server, draft])

  const update = useCallback((mutate: (d: T) => void) => {
    setDraft((prev) => {
      if (prev === null) return prev
      const next = structuredClone(prev)
      mutate(next)
      return next
    })
  }, [])

  const replace = useCallback((next: T) => {
    setDraft(structuredClone(next))
  }, [])

  const discard = useCallback(() => {
    if (server != null) {
      setDraft(structuredClone(server))
      setBaseline(JSON.stringify(server))
    }
  }, [server])

  /** Drop the draft so it re-seeds from the (refetched) server data. */
  const clear = useCallback(() => setDraft(null), [])

  const dirty = draft !== null && JSON.stringify(draft) !== baseline
  return { draft, update, replace, discard, clear, dirty }
}

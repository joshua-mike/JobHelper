import { useEffect, useRef, useState } from 'react'

/**
 * Subscribe to /api/run/logs (SSE). The server replays buffered lines, then
 * follows live output, then emits `done` and we close. `streamKey` should
 * change when a new run starts (e.g. the run's started_at) so the stream
 * reopens and old lines are cleared; pass null to stay disconnected.
 */
export function useRunStream(streamKey: string | null, onDone?: () => void): string[] {
  const [lines, setLines] = useState<string[]>([])
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    if (streamKey == null) return
    setLines([])
    const es = new EventSource('/api/run/logs?after=0')
    es.addEventListener('line', (ev) => {
      const text = JSON.parse((ev as MessageEvent<string>).data) as string
      setLines((prev) => [...prev, text])
    })
    es.addEventListener('done', () => {
      es.close()
      onDoneRef.current?.()
    })
    // On transient errors EventSource reconnects by itself; nothing to do.
    return () => es.close()
  }, [streamKey])

  return lines
}

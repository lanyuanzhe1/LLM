export type SseEventHandler = (event: string, data: unknown) => void

const emitFrame = (frame: string, onEvent: SseEventHandler) => {
  let event = 'message'
  const data: string[] = []

  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }

  if (!data.length) return

  const payload = data.join('\n')

  try {
    onEvent(event, JSON.parse(payload))
  } catch {
    onEvent(event, payload)
  }
}

export const consumeSse = async (response: Response, onEvent: SseEventHandler) => {
  if (!response.body) throw new Error('服务端没有返回可读取的数据流。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()

    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')

    let boundary = buffer.indexOf('\n\n')

    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary).trim()

      buffer = buffer.slice(boundary + 2)
      if (frame) emitFrame(frame, onEvent)
      boundary = buffer.indexOf('\n\n')
    }

    if (done) break
  }

  if (buffer.trim()) emitFrame(buffer.trim(), onEvent)
}

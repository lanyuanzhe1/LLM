import { Suspense } from 'react'

import ChatWorkspace from '@/views/chat/ChatWorkspace'

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatWorkspace />
    </Suspense>
  )
}

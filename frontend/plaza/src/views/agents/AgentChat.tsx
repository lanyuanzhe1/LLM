'use client'

import { Card, CardContent, IconButton, Tooltip, Typography } from '@mui/material'

import type { AgentConfig } from '@/configs/agents'
import AgentChatPanel from '@/views/agents/AgentChatPanel'

const AgentChat = ({ agent }: { agent: AgentConfig }) => {
  const useApiChat = Boolean(agent.assistantId)

  return (
    <Card
      sx={{ height: { xs: 'auto', lg: 'calc(100vh - 150px)' }, minHeight: 640, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
    >
      <CardContent className='flex items-center justify-between gap-4' sx={{ py: 2.5 }}>
        <div className='flex items-center gap-3'>
          <div className='flex h-9 w-9 items-center justify-center rounded text-white' style={{ backgroundColor: agent.color }}>
            <i className={`${agent.icon} text-xl`} />
          </div>
          <div>
            <Typography variant='h5'>{agent.name}</Typography>
            <Typography variant='body2' color='text.secondary'>
              {agent.description}
            </Typography>
          </div>
        </div>
        {agent.url ? (
          <Tooltip title='在新窗口打开'>
            <IconButton component='a' href={agent.url} target='_blank' rel='noopener noreferrer' size='small'>
              <i className='ri-external-link-line' />
            </IconButton>
          </Tooltip>
        ) : null}
      </CardContent>
      {useApiChat ? (
        <AgentChatPanel agent={agent} />
      ) : (
        <iframe src={agent.url} title={agent.name} className='h-full w-full flex-1 border-0' allow='clipboard-write; clipboard-read' />
      )}
    </Card>
  )
}

export default AgentChat

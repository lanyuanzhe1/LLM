'use client'

// PPT 文件卡片 + 页内幻灯片查看器：助手回答的文案经 /api/backend/assistant-pptx/preview
// 解析成结构化分页后，在气泡下渲染文件卡片；点击卡片在 Dialog 里翻阅幻灯片，
// 查看器内可直接下载 .pptx 原文件（与预览同一份解析，页数一致）。
import { useState } from 'react'

import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import IconButton from '@mui/material/IconButton'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'

import { withBasePath } from '@/lib/base-path'

export type PptxPreviewData = {
  title: string
  pages: { heading: string; bullets: string[] }[]
  is_deck: boolean
}

const PptxPreview = ({
  preview,
  color,
  fileName,
  sourceText
}: {
  preview: PptxPreviewData
  color: string
  fileName: string
  sourceText: string
}) => {
  const [open, setOpen] = useState(false)
  const [slideIndex, setSlideIndex] = useState(0)
  const [downloading, setDownloading] = useState(false)

  const totalSlides = 1 + preview.pages.length

  const download = async () => {
    if (downloading) return

    setDownloading(true)

    const response = await fetch(withBasePath('/api/backend/assistant-pptx'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: sourceText, title: preview.title })
    }).catch(() => null)

    if (response?.ok) {
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')

      anchor.href = objectUrl
      anchor.download = fileName
      anchor.click()
      URL.revokeObjectURL(objectUrl)
    }

    setDownloading(false)
  }

  return (
    <>
      <Paper
        variant='outlined'
        onClick={() => {
          setSlideIndex(0)
          setOpen(true)
        }}
        sx={{
          mt: 1.5,
          px: 2,
          py: 1.5,
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          cursor: 'pointer',
          maxWidth: 320,
          '&:hover': { borderColor: color, boxShadow: 1 }
        }}
      >
        <Box
          sx={{
            width: 40,
            height: 40,
            borderRadius: 2,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            flexShrink: 0,
            backgroundColor: color
          }}
        >
          <i className='ri-slideshow-2-line text-xl' />
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant='body2' className='font-semibold' noWrap>
            {fileName}
          </Typography>
          <Typography variant='caption' color='text.secondary'>
            共 {totalSlides} 页 · 点击查看
          </Typography>
        </Box>
        <i className='ri-arrow-right-s-line text-lg' style={{ marginLeft: 'auto', flexShrink: 0 }} />
      </Paper>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth='md' fullWidth>
        <Box sx={{ p: { xs: 2, md: 3 } }}>
          <Box
            sx={{
              aspectRatio: '16/9',
              borderRadius: 2,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              ...(slideIndex === 0
                ? { backgroundColor: color, color: 'white', alignItems: 'center', justifyContent: 'center', textAlign: 'center', px: 6 }
                : { backgroundColor: 'background.paper', border: '1px solid', borderColor: 'divider', px: { xs: 4, md: 8 }, py: { xs: 3, md: 5 } })
            }}
          >
            {slideIndex === 0 ? (
              <>
                <Typography sx={{ fontSize: { xs: 28, md: 44 }, fontWeight: 700, lineHeight: 1.3, color: 'white' }}>{preview.title}</Typography>
                <Typography sx={{ mt: 3, fontSize: { xs: 14, md: 18 }, color: 'white', opacity: 0.85 }}>由智能体生成</Typography>
              </>
            ) : (
              <>
                <Typography sx={{ fontSize: { xs: 20, md: 30 }, fontWeight: 700, mb: { xs: 2, md: 3 } }}>
                  {preview.pages[slideIndex - 1]?.heading}
                </Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: { xs: 1, md: 1.5 }, overflowY: 'auto' }}>
                  {(preview.pages[slideIndex - 1]?.bullets ?? []).map((bullet, index) => (
                    <Box key={index} sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
                      <Box sx={{ width: 8, height: 8, borderRadius: '50%', mt: '0.55em', flexShrink: 0, backgroundColor: color }} />
                      <Typography sx={{ fontSize: { xs: 14, md: 17 }, lineHeight: 1.7 }}>{bullet}</Typography>
                    </Box>
                  ))}
                </Box>
              </>
            )}
          </Box>

          <Box sx={{ mt: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
            <IconButton size='small' disabled={slideIndex === 0} onClick={() => setSlideIndex(i => i - 1)}>
              <i className='ri-arrow-left-s-line' />
            </IconButton>
            <Typography variant='body2' color='text.secondary' sx={{ minWidth: 56, textAlign: 'center' }}>
              {slideIndex + 1} / {totalSlides}
            </Typography>
            <IconButton size='small' disabled={slideIndex >= totalSlides - 1} onClick={() => setSlideIndex(i => i + 1)}>
              <i className='ri-arrow-right-s-line' />
            </IconButton>
            <Box sx={{ flex: 1 }} />
            <Button
              size='small'
              variant='outlined'
              disabled={downloading}
              onClick={() => void download()}
              startIcon={<i className='ri-download-2-line' />}
            >
              {downloading ? '正在生成…' : '下载 .pptx'}
            </Button>
            <Button size='small' variant='contained' onClick={() => setOpen(false)}>
              关闭
            </Button>
          </Box>
        </Box>
      </Dialog>
    </>
  )
}

export default PptxPreview

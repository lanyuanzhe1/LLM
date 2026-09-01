'use client'

import { useEffect, useMemo, useState } from 'react'

import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Grid from '@mui/material/Grid'
import LinearProgress from '@mui/material/LinearProgress'
import MenuItem from '@mui/material/MenuItem'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableContainer from '@mui/material/TableContainer'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import { withBasePath } from '@/lib/base-path'

type KnowledgeData = {
  status: string
  documentCount: number
  chunkCount: number
  dimension: number
  provider: string
  categories: Array<{ name: string; documents: number; chunks: number }>
  documents: Array<{ source: string; category: string; chunks: number }>
}

const categoryIcons: Record<string, string> = {
  其他论文: 'ri-article-line',
  政策文件类: 'ri-government-line',
  新增书本与PPT: 'ri-book-2-line',
  河南工业大学论文: 'ri-school-line'
}

const KnowledgeOverview = () => {
  const [data, setData] = useState<KnowledgeData | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('全部')

  useEffect(() => {
    fetch(withBasePath('/api/knowledge'), { cache: 'no-store' })
      .then(async response => {
        const payload = await response.json()

        if (!response.ok) throw new Error(payload.message || '读取知识库失败')
        setData(payload as KnowledgeData)
      })
      .catch(reason => setError(reason instanceof Error ? reason.message : '读取知识库失败'))
  }, [])

  const filteredDocuments = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase('zh-CN')

    return (data?.documents || []).filter(document => {
      const matchesCategory = category === '全部' || document.category === category
      const matchesQuery = !keyword || document.source.toLocaleLowerCase('zh-CN').includes(keyword)

      return matchesCategory && matchesQuery
    })
  }, [category, data?.documents, query])

  if (error) return <Alert severity='error'>{error}</Alert>
  if (!data) return <LinearProgress />

  return (
    <Grid container spacing={6}>
      <Grid item xs={12}>
        <Card>
          <CardContent className='flex flex-col justify-between gap-5 md:flex-row md:items-center'>
            <div className='flex items-center gap-4'>
              <Avatar variant='rounded' sx={{ width: 56, height: 56, bgcolor: 'primary.lighterOpacity', color: 'primary.main' }}>
                <i className='ri-book-open-line text-3xl' />
              </Avatar>
              <div>
                <Typography variant='h4' className='font-semibold'>课程知识库</Typography>
                <Typography color='text.secondary'>已解析资料及向量片段概览，不在前端重复建立知识库</Typography>
              </div>
            </div>
            <Chip icon={<i className='ri-checkbox-circle-line' />} label='向量库已就绪' color='success' />
          </CardContent>
        </Card>
      </Grid>

      {[
        { label: '已收录资料', value: data.documentCount, unit: '份', icon: 'ri-file-text-line', color: '#8C57FF' },
        { label: '知识片段', value: data.chunkCount, unit: '条', icon: 'ri-node-tree', color: '#4E6BA6' },
        { label: '资料分类', value: data.categories.length, unit: '类', icon: 'ri-folders-line', color: '#C1842B' },
        { label: '向量规格', value: data.dimension, unit: '维', icon: 'ri-bubble-chart-line', color: '#9C5B73' }
      ]
        .filter(item => item.value !== 0)
        .map(item => (
        <Grid item xs={12} sm={6} lg={3} key={item.label}>
          <Card>
            <CardContent className='flex items-center gap-4'>
              <Avatar variant='rounded' sx={{ bgcolor: `${item.color}18`, color: item.color }}>
                <i className={`${item.icon} text-xl`} />
              </Avatar>
              <div>
                <Typography variant='body2' color='text.secondary'>{item.label}</Typography>
                <Typography variant='h5' className='font-semibold'>{item.value} <small>{item.unit}</small></Typography>
              </div>
            </CardContent>
          </Card>
        </Grid>
      ))}

      <Grid item xs={12}>
        <Typography variant='h5' className='mb-4 font-semibold'>资料分类</Typography>
        <Grid container spacing={4}>
          {data.categories.map(item => (
            <Grid item xs={12} sm={6} lg={3} key={item.name}>
              <Card variant='outlined' sx={{ height: '100%' }}>
                <CardContent>
                  <Avatar variant='rounded' sx={{ mb: 3, bgcolor: 'primary.lighterOpacity', color: 'primary.main' }}>
                    <i className={categoryIcons[item.name] || 'ri-folder-line'} />
                  </Avatar>
                  <Typography variant='h6' className='font-semibold'>{item.name}</Typography>
                  <Typography variant='body2' color='text.secondary'>
                    {item.documents} 份资料 · {item.chunks} 个片段
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Grid>

      <Grid item xs={12}>
        <Card>
          <CardContent>
            <div className='mb-5 flex flex-col justify-between gap-4 md:flex-row md:items-center'>
              <div>
                <Typography variant='h5' className='font-semibold'>资料清单</Typography>
                <Typography variant='body2' color='text.secondary'>共显示 {filteredDocuments.length} 份已索引资料</Typography>
              </div>
              <div className='flex flex-col gap-3 sm:flex-row'>
                <TextField
                  size='small'
                  value={query}
                  onChange={event => setQuery(event.target.value)}
                  placeholder='搜索文件名'
                  InputProps={{ startAdornment: <i className='ri-search-line me-2 text-textSecondary' /> }}
                />
                <TextField select size='small' value={category} onChange={event => setCategory(event.target.value)} sx={{ minWidth: 150 }}>
                  <MenuItem value='全部'>全部分类</MenuItem>
                  {data.categories.map(item => <MenuItem key={item.name} value={item.name}>{item.name}</MenuItem>)}
                </TextField>
              </div>
            </div>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>资料名称</TableCell>
                    <TableCell>分类</TableCell>
                    <TableCell align='right'>知识片段</TableCell>
                    <TableCell align='right'>状态</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {filteredDocuments.map(document => (
                    <TableRow key={document.source} hover>
                      <TableCell>
                        <div className='flex items-center gap-3'>
                          <i className='ri-file-pdf-2-line text-xl text-error' />
                          <Typography variant='body2' className='font-medium'>{document.source.split('/').at(-1)}</Typography>
                        </div>
                      </TableCell>
                      <TableCell><Chip label={document.category} size='small' variant='outlined' /></TableCell>
                      <TableCell align='right'>{document.chunks}</TableCell>
                      <TableCell align='right'><Chip label='已索引' size='small' color='success' variant='tonal' /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  )
}

export default KnowledgeOverview
